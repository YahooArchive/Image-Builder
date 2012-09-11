#!/usr/bin/python

# vi: ts=4 expandtab
#
#    Copyright (C) 2012 Yahoo! Inc.
#
#    Author: Joshua Harlow <harlowja@yahoo-inc.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License version 3, as
#    published by the Free Software Foundation.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.


import copy
import hashlib
import json
import optparse
import os
import shutil
import sys
import tarfile
import tempfile
import traceback
import urllib
import urllib2
import uuid

from contextlib import (closing, contextmanager)

from builder import modules
from builder import util

from builder.downloader import tar_ball

import tempita

# Todo allow these to be configurable??
HASH_ROUTINE = 'md5'

# The first partition starts at block 63, and that each block is 512 bytes. 
# So partition 1 starts at byte 32256
PART_OFFSET = 63 * 512


@contextmanager
def cmd_undo(undo_how):
    try:
        yield None
    finally:
        try:
            util.subp(undo_how)
        except:
            pass


def import_module(module_name):
    __import__(module_name)
    return sys.modules[module_name]


def run_modules(root_dir, config):
    config = copy.deepcopy(config)
    mods = config.pop('modules', None)
    if not mods:
        mods = []
    failures = []
    which_ran = []
    for real_name in mods:
        name = real_name.strip()
        name = name.replace('-', '_')
        if not name:
            continue
        try:
            which_ran.append(real_name)
            mod_name = "%s.%s" % (util.obj_name(modules), name)
            mod = import_module(mod_name)
            functor = getattr(mod, 'modify')
            # Give the modules a copy of the config
            # and not the 'real' thing, so that
            # they can't screw it up...
            args = [real_name, root_dir, copy.deepcopy(config)]
            functor(*args)
        except:
            print("Exception in module %r:" % (real_name))
            print('-' * 60)
            traceback.print_exc(file=sys.stdout)
            print('-' * 60)
            failures.append(real_name)
    return (which_ran, failures)


def fix_fstab(root_dir, fstype):
    # /etc/fstab format
    # <file system>        <dir>        
    # <type>    <options>             <dump> <pass>
    lines = [
        '# Generated on %s' % (util.time_rfc2822()),
        '%s%14s%14s%14s%14s%6s' % ('LABEL=root', 
                                   '/', fstype, 'defaults', '0', '0')
    ]
    contents = "\n".join(lines)
    print("Writing a new fstab:")
    print(contents)
    util.write_file(util.abs_join(root_dir, 'etc', 'fstab'),
                    "%s\n" % (contents))


def dd_off(loop_dev, tmp_dir, block_size='32768k'):
    tmp_fn = tempfile.mktemp(dir=tmp_dir, suffix='.raw')
    cmd = [
        'dd',
        'if=%s' % (loop_dev),
        'bs=%s' % (block_size),
        'of=%s' % (tmp_fn),
    ]
    util.subp(cmd, capture=False)
    return tmp_fn


def hash_file(path, out_fn, routine):
    hasher = hashlib.new(routine)

    def hash_cb(_byte_am, chunk):
        hasher.update(chunk)

    base_name = os.path.basename(path)
    with open(path, 'rb') as in_fh:
        byte_size = os.path.getsize(path)
        with open(os.devnull, 'wb') as out_fh:
            util.pretty_transfer(in_fh, out_fh,
                name="%s hashing %s" % (routine.capitalize(), base_name),
                chunk_cb=hash_cb, max_size=byte_size)

    # The md5 sum program produces this output format, so mirror that...
    digest = hasher.hexdigest().lower()
    contents = "%s  %s\n" % (digest, os.path.basename(path))
    util.write_file(out_fn, contents)


def transfer_into_tarball(path, arc_name, tb):
    fns = [arc_name]
    util.print_iterable(fns,
        header="Adding the following to your tarball %s"
               % (util.quote(tb.name)))
    print("Please wait...")
    tb.add(path, arc_name, recursive=False)


def make_virt_xml(kernel_fn, ram_fn, root_fn):
    params = {
        'name': uuid.uuid5(uuid.NAMESPACE_URL,
                          # Just a fake url to get a uuid
                          'http://images.yahoo.com/%s/%s/%s' % 
                          (urllib.quote(root_fn),
                           urllib.quote(kernel_fn),
                           urllib.quote(ram_fn))),
        # 512 MB of ram should be enough for everyone
        'memory': (512 * 1024 * 1024),
        # Add a fake basepath on, to ensure
        # that users replace this since it apparently
        # requires a fully specified path to work
        'kernel': "{basepath}/" + os.path.basename(kernel_fn),
        'initrd': "{basepath}/" + os.path.basename(ram_fn),
        'root': "{basepath}/" + os.path.basename(root_fn),
    }
    tpl_c = util.load_file(util.abs_join('templates', 'virt.xml'))
    tpl = tempita.Template(tpl_c)
    return tpl.substitute(**params)


def ec2_convert(raw_fn, out_fn, out_fmt, strip_partition, compress):
    # Extract the ramdisk/kernel
    devname = create_loopback(raw_fn, PART_OFFSET)
    with util.tempdir() as tdir:
        img_dir = os.path.join(tdir, 'img')
        root_dir = os.path.join(tdir, 'mnt')
        util.ensure_dirs([img_dir, root_dir])
        with cmd_undo(['losetup', '-d', devname]):
            print("Copying off the ramdisk and kernel files.")
            # Mount it
            util.subp(['mount', devname, root_dir])
            with cmd_undo(['umount', root_dir]):
                # Find the right files
                fns = {}
                for fn in os.listdir(util.abs_join(root_dir, 'boot')):
                    if fn.endswith('.img') and fn.startswith('initramfs-'):
                        fns['ramdisk'] = fn
                    if fn.startswith('vmlinuz-'):
                        fns['kernel'] = fn
                    if fn.startswith('initrd-') and fn.endswith('.img'):
                        fns['base'] = fn
                rd_fn = fns.get('ramdisk')
                k_fn = fns.get('kernel')
                if (not rd_fn and not k_fn) and 'base' in fns:
                    kid = fns['base']
                    kid = kid[0:-len('.img')]
                    kid = kid[len('initrd-'):]
                    cmd = ['chroot', root_dir,
                           '/sbin/mkinitrd', '-f',
                           os.path.join('/boot', fns['base']),
                           kid]
                    util.subp(cmd, capture=False)
                    if os.path.isfile(util.abs_join(root_dir, "boot", 
                                     "initramfs-%s.img" % (kid))):
                        rd_fn = "initramfs-%s.img" % (kid)
                    if os.path.isfile(util.abs_join(root_dir, "boot",
                                      "vmlinuz-%s" % (kid))):
                        k_fn = "vmlinuz-%s" % (kid)
                if not rd_fn:
                    raise RuntimeError("No initramfs-*.img file found")
                if not k_fn:
                    raise RuntimeError("No vmlinuz-* file found")
                shutil.move(util.abs_join(root_dir, 'boot', rd_fn), 
                            util.abs_join(img_dir, rd_fn))
                shutil.move(util.abs_join(root_dir, 'boot', k_fn), 
                            util.abs_join(img_dir, k_fn))
            # Copy off the data (minus the partition info)
            if strip_partition:
                print("Stripping off the partition table.")
                print("Please wait...")
                part_stripped_fn = dd_off(devname, tdir)
        # Replace the orginal 'raw' file
        if strip_partition:
            shutil.move(part_stripped_fn, raw_fn)
        # Apply some tune ups
        cmd = [
            'tune2fs',
            # Set the volume label of the filesystem
            '-L', 'root',
            raw_fn
        ]
        util.subp(cmd, capture=False)
        # Convert it to the final format and compress it
        out_base_fn = os.path.basename(out_fn)
        img_fn = out_base_fn
        if img_fn.endswith('.tar.gz'):
            img_fn = img_fn[0:-len('.tar.gz')]
        img_fn += "." + out_fmt
        img_fn = util.abs_join(img_dir, img_fn)
        straight_convert(raw_fn, img_fn, out_fmt)
        # Make a nice helper libvirt.xml file
        util.write_file(util.abs_join(img_dir, 'libvirt.xml'),
                        make_virt_xml(util.abs_join(img_dir, k_fn),
                                      util.abs_join(img_dir, rd_fn),
                                      util.abs_join(img_dir, img_fn)))
        # Give every file written a hash/checksum file
        for fn in os.listdir(img_dir):
            src_fn = util.abs_join(img_dir, fn)
            hash_fn = src_fn + "." + HASH_ROUTINE
            hash_file(src_fn, hash_fn, HASH_ROUTINE)
        # Compress it or just move the folder around
        if compress:
            with closing(tarfile.open(out_fn, 'w:gz')) as tar_fh:
                for fn in os.listdir(img_dir):
                    src_fn = util.abs_join(img_dir, fn)
                    transfer_into_tarball(src_fn, fn, tar_fh)
        else:
            shutil.move(img_dir, out_fn)


def straight_convert(raw_fn, out_fn, out_fmt):
    cmd = ['qemu-img', 'convert', 
           '-f', 'raw',
           '-O', out_fmt,
           raw_fn, out_fn]
    util.subp(cmd, capture=False)


def format_blank(tmp_file_name, size, fs_type):
    print("Creating the image output file %s (scratch-version)." 
              % (util.quote(tmp_file_name)))
    with open(tmp_file_name, 'w+') as o_fh:
        o_fh.truncate(0)
        cmd = ['qemu-img', 'create', '-f', 
               'raw', tmp_file_name, size]
        util.subp(cmd)
    
    # Run fdisk on it
    print("Creating a partition table in %s."
          % (util.quote(tmp_file_name)))

    devname = create_loopback(tmp_file_name)
    with cmd_undo(['losetup', '-d', devname]):
        # See: http://tiny.corp.yahoo.com/4H0lda
        # These are commands to fdisk that will get activated (in order)
        fdisk_in = [
            'n',
            'p',
            '1',
            '1',
            '',
            'w'
        ]
        cmd = ['fdisk', devname]
        util.subp(cmd, data="\n".join(fdisk_in),
                  rcs=[0, 1])
    
    print("Creating a filesystem of type %s in %s." 
          % (util.quote(fs_type), 
             util.quote(tmp_file_name)))

    devname = create_loopback(tmp_file_name, PART_OFFSET)

    # Get a filesystem on it
    with cmd_undo(['losetup', '-d', devname]):
        cmd = ['mkfs.%s' % (fs_type), devname]
        util.subp(cmd)


def create_loopback(filename, offset=None):
    cmd = ['losetup']
    if offset:
        cmd.extend(['-o', str(offset)])
    cmd.extend(['--show', '-f', filename])
    (stdout, _stderr) = util.subp(cmd)
    devname = stdout.strip()
    return devname


def extract_into(tmp_file_name, fs_type, config):
    with util.tempdir() as tdir:
        # Download the image
        # TODO (make this a true module that can be changed...)
        tb_down = tar_ball.TarBallDownloader(dict(config['download']))
        arch_fn = tb_down.download()

        # Extract it
        devname = create_loopback(tmp_file_name, PART_OFFSET)
        with cmd_undo(['losetup', '-d', devname]):
            # Mount it
            root_dir = os.path.join(tdir, 'mnt')
            os.makedirs(root_dir)
            util.subp(['mount', devname, root_dir])
            # Extract it
            with cmd_undo(['umount', root_dir]):
                print("Extracting 'root' tarball %s to %s." % 
                                        (util.quote(arch_fn), 
                                         util.quote(root_dir)))
                util.subp(['tar', '-xzf', arch_fn, '-C', root_dir])
                # Fixup the fstab
                fix_fstab(root_dir, fs_type)


def activate_modules(tmp_file_name, config):
    with util.tempdir() as tdir:
        devname = create_loopback(tmp_file_name, PART_OFFSET)
        with cmd_undo(['losetup', '-d', devname]):
            # Mount it
            root_dir = os.path.join(tdir, 'mnt')
            os.makedirs(root_dir)
            util.subp(['mount', devname, root_dir])
            # Run your modules!
            with cmd_undo(['umount', root_dir]):
                return run_modules(root_dir, config)


def main():
    parser = optparse.OptionParser()
    parser.add_option("-s", '--size', dest="size",
                      metavar="SIZE",
                      help="image size (qemu-img understandable)")
    parser.add_option("-o", '--output', dest="file_name",
                      metavar="FILE",
                      help="output filename")
    parser.add_option('--fs-type', dest="fs_type",
                      metavar="FILESYSTEM",
                      default='ext4',
                      help=("filesystem type to create"
                            ' (default: %default)'))
    parser.add_option('-c', '--config',
                      metavar='FILE',
                      dest='config',
                      action='store',
                      default=os.path.join(os.getcwd(), "build.yaml"),
                      help=("yaml config file"
                           " (default: %default)"))
    parser.add_option('-x', '--compress',
                      dest='compress',
                      action='store_true',
                      default=False,
                      help=("compress the created image set"
                           " (default: %default)"))
    parser.add_option('--strip',
                      dest='strip_parts',
                      action='store_false',
                      default=True,
                      help=("strip the image partition table"
                           " (default: %default)"))
    (options, _args) = parser.parse_args()
    
    # Ensure options are ok
    if not options.size:
        parser.error("Option -s is required")
    if not options.file_name:
        parser.error("Option -o is required")
    if not options.config:
        parser.error("Option -c is required")

    full_fn = os.path.abspath(options.file_name)
    final_format = 'qcow2'

    config = {}
    with open(options.config, 'r') as fh:
        config = util.load_yaml(fh.read())

    print("Loaded builder config from %s:" % (util.quote(options.config)))
    print(json.dumps(config, sort_keys=True, indent=4))
    with tempfile.NamedTemporaryFile(suffix='.raw') as tfh:
        tmp_file_name = tfh.name
        format_blank(tmp_file_name, options.size, options.fs_type)
        extract_into(tmp_file_name, options.fs_type, config)

        (ran, fails) = activate_modules(tmp_file_name, config)
        if len(fails):
            fail_am = util.quote(str(len(fails)), quote_color='red')
        else:
            fail_am = '0'
        print("Ran %s modules with %s failures." % (len(ran), fail_am))
        if len(fails):
            print(("Not performing scratch to final image"
                   " conversion due to %s failures!!") % (fail_am))
            return len(fails)

        print("Converting %s to final file %s." %
              (util.quote(tmp_file_name), util.quote(full_fn)))
        ec2_convert(tmp_file_name, full_fn, final_format,
                    options.strip_parts, options.compress)
        return 0


if __name__ == '__main__':
    rc = main()
    print("Goodbye...[%s]" % (rc))
    sys.exit(rc)


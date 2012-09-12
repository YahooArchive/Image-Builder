# vi: ts=4 expandtab
#
#    Copyright (C) 2012 Yahoo! Inc. All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.



import os

from builder import util


def expand_rpms(potential_rpms):
    if not potential_rpms:
        return None
    rpms_expanded = []
    for rpm in potential_rpms:
        if os.path.isfile(rpm):
            rpms_expanded.append(rpm)
        elif os.path.isdir(rpm):
            base_dir = rpm
            for fn in os.listdir(base_dir):
                full_fn = os.path.join(base_dir, fn)
                if full_fn.endswith('.rpm') and os.path.isfile(full_fn):
                    rpms_expanded.append(full_fn)
    return rpms_expanded


def modify(name, root, cfg):
    rpms = expand_rpms(cfg.get('rpms'))
    if not rpms:
        return
    util.print_iterable(rpms,
                        header=("Installing the following rpms"
                                " in module %s" % (util.quote(name))))
    util.ensure_dir(util.abs_join(root, 'tmp'))
    cleanup_fns = []
    for fn in rpms:
        cp_to = util.abs_join(root, 'tmp', os.path.basename(fn))
        util.copy(fn, cp_to)
        cleanup_fns.append(cp_to)
    real_fns = []
    for fn in rpms:
        real_fns.append(os.path.join('/tmp', os.path.basename(fn)))
    cmd = ['chroot', root,
           'yum', '--nogpgcheck', '-y',
           'localinstall']
    cmd.extend(real_fns)
    try:
        util.subp(cmd, capture=False)
    finally:
        # Ensure cleaned up
        for fn in cleanup_fns:
            util.del_file(fn)

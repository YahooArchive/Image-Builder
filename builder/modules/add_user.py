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



import os

from builder import util


def modify(name, root, cfg):
    user_names = cfg.get('add_users')
    if not user_names:
        return
    util.print_iterable(user_names,
                        header="Adding the following users in module %s" %
                        (util.quote(name)))
    for uname in user_names:
        cmd = ['chroot', root,
               'yinst', 'i', '-yes',
               'admin/sudo-%s' % (uname)]
        util.subp(cmd, capture=False)

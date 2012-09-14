*Imaging Hot Sauce*
========


Description
--------

Modular image builder for imaging awesomeness!

Goals
----

1. Make it easy to create EC2 style images (root, kernel, ramdisk *like*)
1. Allow for vsing varying *sources* of those images (right now just a *tarball* of a installed / partition)
1. Make it easy to add in custom logic on-top of those images via a modular set of python code that you can easily extend
1. Keep it small, sane, clean and flexible

Status
--------

1. Needs love and tender care (it is mostly a prototype)


Default modules
--------

1. add_user (adds a given set of sudo users)
1. install_rpms (installs a list of rpm packages)
...
1000. Your imagination...

Examples
---- 

    $ sudo python ./build.py -s 4G

To add users make a yaml like the following:

    $ cat build.yaml 
    
    ---
    # Which modules should be ran (in order)
    modules:
      - install-rpms
      - add_user
    
    # Enable this if you wish to install
    # any users info into the image (ie for testing).
    add_users: 
       - harlowja
    
    ...

Then run:

    $ sudo python ./build.py  -s 4G -o blah.tar.gz -x

Adding your own module
---- 

To add your own module create a file in the `modules` folder with a function
of the following format:

    def modify(name, root, cfg):
       # DO SOMETHING HERE
    
The `name` that is passed in will be the module name (from configuration) with
the `root` variable being the root directory of the mounted image (useful for `chroot`) 
or other file alterations and the `cfg` variable will be the build configuration 
dictionary (useful for extracting any module configuration specifics)

Then save this file with a given name, ie ``xyz.py``, and then to get this module
to be activated add it to the modules list in the ``build.yaml`` file with the name
``xyz`` and then go ahead and build your image. 

**Note:** If this module errors out (or other modules do the same) the image
will not be successfully built so use this method to stop image building (ie
by throwing exceptions).

Using your image
----

To upload this image, take the `image-upload` tool in [anvil](http://anvil.readthedocs.org/) (or use the glance-client
itself, either or) and provide it the url of your file, for example given a 
archive at `/homes/harlowja/blah.tar.gz` you would upload this via the following command.

    $ python tools/img-uploader.py  -i file://///homes/harlowja/blah.tar.gz 
                                    -g $GLANCE_URI -k $KEYSTONE_URI 
                                    -u $YOUR_USER -t $YOUR_TENANT

Using the  `image-upload` tool will go through the *nitty gritty* of extracting that
image and connecting the pieces together to form a useable image in openstack. You
can of course do the same with the [glance-client](https://github.com/openstack/python-glanceclient)
(although you will have to know the special invocations to achieve the same effect as the `image-upload` tool performs).

**Note:** The image produced should also be easily useable in amazon (if someone ever
gets around to trying that...).


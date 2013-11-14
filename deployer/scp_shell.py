from deployer.cli import CLInterface, Handler, HandlerType
from deployer.console import Console
from deployer.exceptions import ActionException
from deployer.host import Host
from deployer.node import Env
from deployer.utils import esc1

import sys
import os
import stat
import os.path

# Types

class BuiltinType(HandlerType):
    color = 'cyan'

class LocalType(HandlerType):
    color = 'green'

class RemoteType(HandlerType):
    color = 'yellow'

class ModifyType(HandlerType):
    color = 'red'


# Handlers

class SCPHandler(Handler):
    def __init__(self, shell):
        self.shell = shell

def remote_handler(files_only=False, directories_only=False):
    """ Create a node system that does autocompletion on the remote path. """
    def autocomplete_directory(shell):
        cwd = shell.host.getcwd()
        if cwd:
            if cwd in shell._cd_cache:
                return shell._cd_cache[cwd]
            else:
                files = shell.host.listdir()
                shell._cd_cache[cwd] = files
                return files
        else:
            return []

    def is_file(shell, f):
        return shell.host.stat(f).is_file

    def is_dir(shell, f):
        return shell.host.stat(f).is_dir

    return _create_autocompleter_system(files_only, directories_only, RemoteType,
            autocomplete_directory, is_file, is_dir)


def local_handler(files_only=False, directories_only=False):
    """ Create a node system that does autocompletion on the local path. """
    return _create_autocompleter_system(files_only, directories_only, LocalType,
            lambda shell: os.listdir(os.getcwd()),
            lambda shell, f: os.path.isfile(f),
            lambda shell, f: os.path.isdir(f))


def _create_autocompleter_system(files_only, directories_only, handler_type_cls, listdir, isfile, isdir):
    def local_handler(func):
        class ChildHandler(SCPHandler):
            is_leaf = True

            def __init__(self, shell, path):
                self.path = path
                SCPHandler.__init__(self, shell)

            def __call__(self):
                func(self.shell, self.path)

        class MainHandler(SCPHandler):
            handler_type = handler_type_cls()

            def complete_subhandlers(self, part):
                for f in listdir(self.shell):
                    if f.startswith(part):
                        if files_only and not isfile(self.shell, f):
                            continue
                        if directories_only and not isdir(self.shell, f):
                            continue

                        yield f, ChildHandler(self.shell, f)

                # Root directory.
                if '/'.startswith(part) and not files_only:
                    yield f, ChildHandler(self.shell, '/')

            def get_subhandler(self, name):
                return ChildHandler(self.shell, name)

        return MainHandler
    return local_handler

class Clear(SCPHandler):
    """ Clear window.  """
    is_leaf = True
    handler_type = BuiltinType()

    def __call__(self):
        sys.stdout.write('\033[2J\033[0;0H')
        sys.stdout.flush()

class Exit(SCPHandler):
    """ Quit the SFTP shell. """
    is_leaf = True
    handler_type = BuiltinType()

    def __call__(self):
        self.shell.exit()


class Connect(SCPHandler):
    is_leaf = True
    handler_type = BuiltinType()

    def __call__(self): # XXX: code duplication of deployer/shell.py
        from deployer.contrib.nodes import connect

        class Connect(connect.Connect):
            initial_input = "cd '%s'\n" % esc1(self.shell.host.getcwd() or '.')

            class Hosts:
                host = self.shell.host.__class__

        env = Env(Connect(), self.shell.pty, self.shell.logger_interface)
        try:
            env.with_host()
        except ActionException as e:
            pass

@remote_handler(files_only=True)
def display(shell, path):
    """ Display remote file. """
    console = Console(shell.pty)

    with shell.host.open(path, 'r') as f:
        def reader():
            while True:
                line = f.readline()
                if line:
                    yield line.rstrip('\n')
                else:
                    return # EOF

        console.lesspipe(reader())


class Pwd(SCPHandler):
    """ Display remote working directory. """
    is_leaf = True
    handler_type = RemoteType()

    def __call__(self):
        print self.shell.host.getcwd()


class Ls(SCPHandler):
    """ Display a remote directory listing """
    is_leaf = True
    handler_type = RemoteType()

    def __call__(self):
        try:
            files = self.shell.host.listdir()
            console = Console(self.shell.pty)
            console.lesspipe(console.in_columns(files))
        except Exception as e:
            # IOError: permission denied.
            print 'ERROR: ', e


@remote_handler(directories_only=True)
def cd(shell, path):
    try:
        shell.host.host_context._chdir(path)
    except Exception as e: # TODO: generic exception handlers.
        # IOError: No such file or directory.
        # paramiko.SFTPError: Not a directory.
        print 'ERROR: ', e


@local_handler(directories_only=True)
def lcd(shell, path):
    try:
        os.chdir(path)
        print os.getcwd()
    except Exception as e:
        print 'ERROR: ', e


class Lls(SCPHandler):
    """ Display local directory listing  """
    handler_type = LocalType()
    is_leaf = True

    def __call__(self):
        files = os.listdir(os.getcwd())
        console = Console(self.shell.pty)
        console.lesspipe(console.in_columns(files))


class Lpwd(SCPHandler):
    """ Print local working directory. """
    handler_type = LocalType()
    is_leaf = True

    def __call__(self):
        print os.getcwd()


@local_handler(files_only=True)
def ldisplay(shell, path):
    """ Display local file. """
    console = Console(shell.pty)

    with open(path, 'r') as f:
        def reader():
            while True:
                line = f.readline()
                if line:
                    yield line.rstrip('\n')
                else:
                    return # EOF

        console.lesspipe(reader())

@local_handler(files_only=True)
def put(shell, path):
    """ Upload local-path and store it on the remote machine. """
    print 'TODO: put', path


@remote_handler(files_only=True)
def get(shell, filename):
    """ Retrieve the remote-path and store it on the local machine """
    print 'Downloading %s...' % filename
    h = shell.host
    h.get_file(os.path.join(h.getcwd(), filename), # TODO: wrap this in an SCPOperationNode.
            os.path.join(os.getcwd(), filename), logger=shell.logger_interface)

@remote_handler()
def stat_handler(shell, filename):
    """ Print stat information of this file. """
    s = shell.host.stat(filename)

    print ' Is file:      %r' % s.is_file
    print ' Is directory: %r' % s.is_dir
    print
    print ' Size:         %r bytes' % s.st_size
    print
    print ' st_uid:       %r' % s.st_uid
    print ' st_gid:       %r' % s.st_gid
    print ' st_mode:      %r' % s.st_mode


@local_handler()
def lstat(shell, filename):
    """ Print stat information for this local file. """
    path = os.path.join(os.getcwd(), filename)
    s =  os.stat(path)

    print ' Is file:      %r' % stat.S_ISREG(s.st_mode)
    print ' Is directory: %r' % stat.S_ISDIR(s.st_mode)
    print
    print ' Size:         %r bytes' % int(s.st_size)
    print
    print ' st_uid:       %r' % s.st_uid
    print ' st_gid:       %r' % s.st_gid
    print ' st_mode:      %r' % s.st_mode


class RootHandler(SCPHandler):
    subhandlers = {
            'clear': Clear,
            'exit': Exit,
            'connect': Connect,

            'ls': Ls,
            'cd': cd,
            'pwd': Pwd,
            'stat': stat_handler,
            'display': display,

            'lls': Lls,
            'lcd': lcd,
            'lpwd': Lpwd,
            'lstat': lstat,
            'ldisplay': ldisplay,

            'put': put,
            'get': get,
    }

    def complete_subhandlers(self, part):
        # Built-ins
        for name, h in self.subhandlers.items():
            if name.startswith(part):
                yield name, h(self.shell)

    def get_subhandler(self, name):
        if name in self.subhandlers:
            return self.subhandlers[name](self.shell)



class Shell(CLInterface):
    """
    Interactive secure copy shell.
    """
    def __init__(self, pty, host, logger_interface, clone_shell=None): # XXX: import clone_shell
        assert issubclass(host, Host)

        self.host = host()
        self.logger_interface = logger_interface
        self.pty = pty
        self.root_handler = RootHandler(self)

        CLInterface.__init__(self, self.pty, RootHandler(self))

        # Caching for autocompletion (directory -> list of content.)
        self._cd_cache = { }

    @property
    def prompt(self):
        get_name = lambda p: os.path.split(p)[-1]

        return [
                    ('local:%s' % get_name(os.getcwd()), 'yellow'),
                    (' ~ ', 'cyan'),
                    ('%s:' % self.host.slug, 'yellow'),
                    (get_name(self.host.getcwd() or ''), 'yellow'),
                    (' > ', 'cyan'),
                ]

# tasks.py - top-level fabric tasks: from pyappconfig.tasks import *

"""
fabric tasks
------------

We use the following mechanism to provide common task implementations for all clld apps:
This module defines and exports tasks which take a first argument "environment".
The environment is used to determine the correct host to run the actual task on.
To connect tasks to a certain app, the app's fabfile needs to import this module
and run the init function, passing an app name defined in the global clld app config.
"""

from __future__ import unicode_literals

import os
import time
import json
import functools
from getpass import getpass
from datetime import datetime, timedelta
from importlib import import_module

from ._compat import input, pathlib

from fabric.api import env, task, execute, settings, sudo, run, cd, local
from fabric.contrib.console import confirm
from fabric.contrib.files import exists
from fabtools import require, service, postgres
from fabtools.files import upload_template
from fabtools.python import virtualenv
from pytz import timezone, utc

from . import TEMPLATE_DIR, PKG_DIR, config, varnish, tools

__all__ = [
    'task_host_from_environment',
    'init',
    'pipfreeze',
    'bootstrap', 'deploy', 'uninstall',
    'start', 'stop', 'maintenance',
    'cache', 'uncache',
    'create_downloads', 'copy_downloads', 'copy_rdfdump',
    'run_script',
]

APP = None


env.use_ssh_config = True


def init(app_name=None):
    global APP
    if app_name is None:
        app_name = tools.caller_dirname()
    APP = config.APPS[app_name]


def task_host_from_environment(func_or_environment):
    if callable(func_or_environment):
        func, _environment = func_or_environment, None
    else:
        func, _environment = None, func_or_environment
    if func is not None:
        @functools.wraps(func)
        def wrapper(environment, *args, **kwargs):
            assert environment in ('production', 'test')
            if not env.hosts:
                # This allows overriding the configured hosts by explicitly passing a host for
                # the task using fab's -H option.
                env.hosts = [getattr(APP, environment)]
            env.environment = environment
            return execute(func, APP, *args, **kwargs)
        wrapper.inner_func = func
        return task(wrapper)
    else:
        def decorator(func):
            _wrapper = task_host_from_environment(func).wrapped
            wrapper = functools.wraps(_wrapper)(functools.partial(_wrapper, _environment))
            wrapper.inner_func = _wrapper.inner_func
            return task(wrapper)
        return decorator


@task
def bootstrap():  # pragma: no cover
    for pkg in ['vim', 'tree', 'nginx', 'open-vm-tools']:
        require.deb.package(pkg)


@task_host_from_environment
def stop(app):
    """stop app by changing the supervisord config"""
    execute(supervisor, app, 'pause')


@task_host_from_environment
def start(app):
    """start app by changing the supervisord config"""
    execute(supervisor, app, 'run')


def supervisor(app, command, template_variables=None):
    """
    .. seealso: http://serverfault.com/a/479754
    """
    template_variables = template_variables or get_template_variables(app)
    template_variables['PAUSE'] = {'pause': True, 'run': False}[command]
    upload_template_as_root(
        app.supervisor, 'supervisor.conf', template_variables, mode='644')
    if command == 'run':
        sudo('supervisorctl reread')
        sudo('supervisorctl update %s' % app.name)
        sudo('supervisorctl restart %s' % app.name)
    else:
        sudo('supervisorctl stop %s' % app.name)
        #sudo('supervisorctl reread %s' % app.name)
        #sudo('supervisorctl update %s' % app.name)
    time.sleep(1)


def get_template_variables(app, monitor_mode=False, with_blog=False):
    res = dict(
        app=app,
        env=env,
        gunicorn=app.bin('gunicorn_paster'),
        monitor_mode=monitor_mode,
        auth='',
        bloghost='',
        bloguser='',
        blogpassword='')

    if with_blog:  # pragma: no cover
        for key, default in [
            ('bloghost', 'blog.%s' % app.domain),
            ('bloguser', app.name),
            ('blogpassword', ''),
        ]:
            res[key] = os.environ.get(('%s_%s' % (app.name, key)).upper(), '')
            if not res[key]:
                custom = get_input('Blog %s [%s]: ' % (key[4:], default))
                res[key] = custom if custom else default
        assert res['blogpassword']

    return res


@task_host_from_environment('production')
def cache(app):
    """"""
    execute(varnish.cache, app)


@task_host_from_environment('production')
def uncache(app):
    execute(varnish.uncache, app)


@task_host_from_environment
def maintenance(app, hours=2, template_variables=None):
    """create a maintenance page giving a date when we expect the service will be back

    :param hours: Number of hours we expect the downtime to last.
    """
    template_variables = template_variables or get_template_variables(app)
    ts = utc.localize(datetime.utcnow() + timedelta(hours=hours))
    ts = ts.astimezone(timezone('Europe/Berlin')).strftime('%Y-%m-%d %H:%M %Z%z')
    template_variables['timestamp'] = ts
    require.files.directory(str(app.www), use_sudo=True)
    upload_template_as_root(
        app.www.joinpath('503.html'), '503.html', template_variables)


@task_host_from_environment
def deploy(app, with_blog=False, with_alembic=False, with_files=True):
    """deploy the app"""
    if not with_blog:
        with_blog = getattr(app, 'with_blog', False)
    with settings(warn_only=True):
        lsb_release = run('lsb_release -a')
    for codename in ['trusty', 'precise', 'xenial']:
        if codename in lsb_release:
            lsb_release = codename
            break
    else:
        if lsb_release != '{"status": "ok"}':
            # if this were the case, we'd be in a test!
            raise ValueError('unsupported platform: %s' % lsb_release)

    if env.environment == 'test' and app.workers > 3:
        app.workers = 3

    template_variables = get_template_variables(
        app,
        monitor_mode='true' if env.environment == 'production' else 'false',
        with_blog=with_blog)

    require.users.user(app.name, shell='/bin/bash')
    #require.postfix.server(env['host'])
    require.postgres.server()
    require.deb.package('default-jre' if lsb_release == 'xenial' else 'openjdk-6-jre')
    require.deb.packages(app.require_deb)
    require.postgres.user(app.name, app.name)
    require.postgres.database(app.name, app.name)
    require.files.directory(str(app.venv), use_sudo=True)

    if getattr(app, 'pg_unaccent', False):
        require.deb.packages(['postgresql-contrib'])
        sudo('sudo -u postgres psql -c "{0}" -d {1.name}'.format(
            'CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public;',
            app))

    with_pg_collkey = getattr(app, 'pg_collkey', False)
    if with_pg_collkey:
        pg_version = '9.1' if lsb_release == 'precise' else '9.3'
        if not exists('/usr/lib/postgresql/%s/lib/collkey_icu.so' % pg_version):
            require.deb.packages(['postgresql-server-dev-%s' % pg_version, 'libicu-dev'])
            upload_template_as_root(
                '/tmp/Makefile', 'pg_collkey_Makefile', dict(pg_version=pg_version))

            require.files.file(
                '/tmp/collkey_icu.c',
                source=os.path.join(
                    os.path.dirname(__file__), 'pg_collkey-v0.5', 'collkey_icu.c'))
            with cd('/tmp'):
                sudo('make')
                sudo('make install')
        init_pg_collkey(app)

    if lsb_release == 'precise':
        require.deb.package('python-dev')
        require.python.virtualenv(str(app.venv), use_sudo=True)
    else:
        require.deb.package('python3-dev')
        require.deb.package('python-virtualenv')
        if not exists(str(app.venv.joinpath('bin'))):
            sudo('virtualenv -q --python=python3 %s' % app.venv)

    require.files.directory(str(app.logs), use_sudo=True)

    with virtualenv(str(app.venv)):
        require.python.pip('6.0.6')
        sp = env['sudo_prefix']
        env['sudo_prefix'] += ' -H'  # set HOME for pip log/cache
        require.python.packages(app.require_pip, use_sudo=True)
        for name in [app.name] + getattr(app, 'dependencies', []):
            pkg = '-e git+git://github.com/clld/%s.git#egg=%s' % (name, name)
            require.python.package(pkg, use_sudo=True)
        env['sudo_prefix'] = sp
        sudo('webassets -m %s.assets build' % app.name)
        res = sudo('python -c "import clld; print(clld.__file__)"')
        assert res.startswith('/usr/venvs') and '__init__.py' in res
        template_variables['clld_dir'] = '/'.join(res.split('/')[:-1])

    require_bibutils(app)

    #
    # configure nginx:
    #
    require.files.directory(
        os.path.dirname(str(app.nginx_location)),
        owner='root', group='root', use_sudo=True)

    restricted, auth = http_auth(app)
    if restricted:
        template_variables['auth'] = auth
    template_variables['admin_auth'] = auth

    if env.environment == 'test':
        upload_template_as_root('/etc/nginx/sites-available/default', 'nginx-default.conf')
        template_variables['SITE'] = False
        upload_template_as_root(
            app.nginx_location, 'nginx-app.conf', template_variables)
    elif env.environment == 'production':
        template_variables['SITE'] = True
        upload_template_as_root(app.nginx_site, 'nginx-app.conf', template_variables)
        upload_template_as_root(
            '/etc/logrotate.d/{0}'.format(app.name), 'logrotate.conf', template_variables)

    maintenance.inner_func(app, hours=app.deploy_duration, template_variables=template_variables)
    service.reload('nginx')

    if not with_alembic and confirm('Recreate database?', default=False):
        db_name = get_input('from db [{0.name}]: '.format(app))
        local('pg_dump -x -O -f /tmp/{0.name}.sql {1}'.format(app, db_name or app.name))
        local('gzip -f /tmp/{0.name}.sql'.format(app))
        require.files.file(
            '/tmp/{0.name}.sql.gz'.format(app),
            source="/tmp/{0.name}.sql.gz".format(app))
        sudo('gunzip -f /tmp/{0.name}.sql.gz'.format(app))
        supervisor(app, 'pause', template_variables)

        if postgres.database_exists(app.name):
            with cd('/var/lib/postgresql'):
                sudo('sudo -u postgres dropdb %s' % app.name)

            require.postgres.database(app.name, app.name)
            if with_pg_collkey:
                init_pg_collkey(app)

        sudo('sudo -u {0.name} psql -f /tmp/{0.name}.sql -d {0.name}'.format(app))
    else:
        if exists(app.src.joinpath('alembic.ini')):
            if confirm('Upgrade database?', default=False):
                # Note: stopping the app is not strictly necessary, because the alembic
                # revisions run in separate transactions!
                supervisor(app, 'pause', template_variables)
                with virtualenv(str(app.venv)):
                    with cd(str(app.src)):
                        sudo('sudo -u {0.name} {1} -n production upgrade head'.format(
                            app, app.bin('alembic')))

                if confirm('Vacuum database?', default=False):
                    if confirm('VACUUM FULL?', default=False):
                        sudo('sudo -u postgres vacuumdb -f -z -d %s' % app.name)
                    else:
                        sudo('sudo -u postgres vacuumdb -z -d %s' % app.name)

    template_variables['TEST'] = {'test': True, 'production': False}[env.environment]
    # We only set add a setting clld.files, if the corresponding directory exists;
    # otherwise the app would throw an error on startup.
    template_variables['files'] = False
    if exists(app.www.joinpath('files')):
        template_variables['files'] = app.www.joinpath('files')
    upload_template_as_root(app.config, 'config.ini', template_variables)

    supervisor(app, 'run', template_variables)

    time.sleep(5)
    res = run('curl http://localhost:%s/_ping' % app.port)
    assert json.loads(res)['status'] == 'ok'


def get_input(prompt):  # to facilitate mocking
    return input(prompt)


def upload_template_as_root(dest, template, context=None, mode=None, owner='root'):
    if mode is not None:
        mode = int(mode, 8)
    upload_template(template, str(dest), context, use_jinja=True,
                    template_dir=TEMPLATE_DIR.as_posix(), use_sudo=True, backup=False,
                    mode=mode, chown=True, user=owner)


def init_pg_collkey(app):
    require.files.file(
        '/tmp/collkey_icu.sql',
        source=os.path.join(
            os.path.dirname(__file__), 'pg_collkey-v0.5', 'collkey_icu.sql'))
    sudo('sudo -u postgres psql -f /tmp/collkey_icu.sql -d {0.name}'.format(app))


def require_bibutils(app):  # pragma: no cover
    """
    tar -xzvf bibutils_5.0_src.tgz -C /home/{app.name}
    cd /home/{app.name}/bibutils_5.0
    configure
    make
    sudo make install
    """
    if not exists('/usr/local/bin/bib2xml'):
        target = '/tmp/bibutils_5.0_src.tgz'
        require.files.file(
            target,
            source=(PKG_DIR / 'bibutils' / 'bibutils_5.0_src.tgz').as_posix(),
            use_sudo=True)

        sudo('tar -xzvf {tgz} -C {app.home}'.format(tgz=target, app=app))
        with cd(str(app.home.joinpath('bibutils_5.0'))):
            sudo('./configure')
            sudo('make')
            sudo('make install')


def http_auth(app):
    pwds = {
        app.name: getpass(prompt='HTTP Basic Auth password for user %s: ' % app.name),
        'admin': ''}

    while not pwds['admin']:
        pwds['admin'] = getpass(prompt='HTTP Basic Auth password for user admin: ')

    for i, pair in enumerate([(n, p) for n, p in pwds.items() if p]):
        opts = 'bd'
        if i == 0:
            opts += 'c'
        sudo('htpasswd -%s %s %s %s' % (opts, app.nginx_htpasswd, pair[0], pair[1]))

    return bool(pwds[app.name]), """\
        proxy_set_header Authorization $http_authorization;
        proxy_pass_header  Authorization;
        auth_basic "%s";
        auth_basic_user_file %s;""" % (app.name, app.nginx_htpasswd)


@task_host_from_environment
def pipfreeze(app):
    """get installed versions"""
    with virtualenv(app.venv):
        stdout = run('pip freeze')

    def iterlines(lines):
        warning = ('\x1b[33m', 'You should ')
        app_git = '%s.git' % app.name.lower()
        ignore = {'babel', 'fabric', 'fabtools', 'newrelic', 'paramiko', 'pycrypto', 'pyx'}
        for line in lines:
            if line.startswith(warning):
                continue  # https://github.com/pypa/pip/issues/2470
            elif app_git in line or line.partition('==')[0].lower() in ignore:
                continue
            elif 'clld.git' in line:
                line = 'clld'
            elif 'clldmpg.git' in line:
                line = 'clldmpg'
            yield line + '\n'

    with open('requirements.txt', 'w') as fp:
        fp.writelines(iterlines(stdout.splitlines()))


@task_host_from_environment
def uninstall(app):  # pragma: no cover
    """uninstall the app"""
    for file_ in [app.supervisor, app.nginx_location, app.nginx_site]:
        file_ = str(file_)
        if exists(file_):
            sudo('rm %s' % file_)
    service.reload('nginx')
    sudo('supervisorctl stop %s' % app.name)


@task_host_from_environment
def create_downloads(app):
    """create all configured downloads"""
    dl_dir = app.src.joinpath(app.name, 'static', 'download')
    require.files.directory(dl_dir, use_sudo=True, mode="777")
    # run the script to create the exports from the database as glottolog3 user
    run_script(app, 'create_downloads')
    require.files.directory(dl_dir, use_sudo=True, mode="755")


@task_host_from_environment
def copy_downloads(app, pattern='*'):
    """copy downloads for the app"""
    dl_dir = app.src.joinpath(app.name, 'static', 'download')
    require.files.directory(dl_dir, use_sudo=True, mode="777")
    local_dl_dir = pathlib.Path(import_module(app.name).__file__).parent.joinpath('static', 'download')
    for f in local_dl_dir.glob(pattern):
        target = dl_dir.joinpath(f.name)
        create_file_as_root(target, open(f.as_posix()).read())
        sudo('chown %s:%s %s' % (app.name, app.name, target))
    require.files.directory(dl_dir, use_sudo=True, mode="755")


def create_file_as_root(path, content, **kw):
    kw.setdefault('owner', 'root')
    kw.setdefault('group', 'root')
    require.files.file(str(path), contents=content, use_sudo=True, **kw)


@task_host_from_environment
def copy_rdfdump(app):
    """copy rdfdump for the app"""
    execute(copy_downloads(app, pattern='*.n3.gz'))


@task_host_from_environment
def run_script(app, script_name, *args):  # pragma: no cover
    """"""
    with cd(str(app.home)):
        sudo(
            '%s %s %s#%s %s' % (
                app.bin('python'),
                app.src.joinpath(app.name, 'scripts', '%s.py' % script_name),
                os.path.basename(str(app.config)),
                app.name,
                ' '.join('%s' % arg for arg in args),
            ),
            user=app.name)

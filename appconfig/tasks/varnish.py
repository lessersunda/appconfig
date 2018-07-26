# varnish.py - install, configure, and run varnish cache

from fabric.api import settings, run
from fabtools import require, files, service

from . import task_app_from_environment
from . import deployment  # FIXME

__all__ = ['cache', 'uncache']

PORT = 6081


@task_app_from_environment('production')
def cache(app):
    """require an app to be put behind varnish

    - apt-get install varnish
    - create /etc/default/varnish
    - create /etc/varnish/main.vcl
    - create /etc/varnish/sites/
    - create /etc/varnish/sites/{app.name}.vcl
    - create /etc/varnish/sites.vcl
      (and require it to contain the correct include!)
    - /etc/init.d/varnish restart
    - adapt nginx site config
    - /etc/init.d/nginx reload
    """
    require.deb.package('varnish')

    deployment.sudo_upload_template('varnish', dest='/etc/default/varnish')
    deployment.sudo_upload_template('varnish_main.vcl', dest='/etc/varnish/main.vcl')

    require.directory(str(app.varnish_site.parent), use_sudo=True)
    deployment.sudo_upload_template('varnish_site.vcl', dest=str(app.varnish_site),
                                    app_name=app.name, app_port=app.port,
                                    app_domain=app.domain)

    _update_varnish_sites(app.varnish_site.parent)

    _update_nginx(app, with_varnish=True)


@task_app_from_environment('production')
def uncache(app):
    with settings(warn_only=True):
        files.remove(str(app.varnish_site), use_sudo=True)

    _update_varnish_sites(app.varnish_site.parent)

    _update_nginx(app, with_varnish=False)


def _update_varnish_sites(directory):
    sites = run('find %s -mindepth 1 -maxdepth 1 -type f ' % directory,
                combine_stderr=False).splitlines()
    includes =  ''.join('include "%s";\n' % s for s in sites)
    # work around requrie.files(contents='') not replacing
    contents = '# autogenerated\n%s' % includes
    require.file('/etc/varnish/sites.vcl', contents=contents, use_sudo=True, mode='644')
    service.restart('varnish')


def _update_nginx(app, with_varnish=True, varnish_port=PORT):
    if with_varnish:
        app = app.replace(port=varnish_port)
    ctx = deployment.template_context(app)
    deployment.require_nginx(ctx)
    service.reload('nginx')

from fabric.api import run, task, sudo, settings
from fabric.tasks import execute
from fabtools import python

from appconfig import APPS_DIR, APPS
from appconfig.config import App


def pip_freeze(app):
    with python.virtualenv(str(app.venv_dir)):
        stdout = run('pip freeze', combine_stderr=False)

    def iterlines(lines):
        for line in lines:
            yield line + '\n'

    target = APPS_DIR / app.name / 'requirements.txt'

    with target.open('w', encoding='ascii') as fp:
        fp.writelines(iterlines(stdout.splitlines()))


@task
def ls():
    """list installed clld apps"""
    sudo('supervisorctl avail')
    sudo('psql -l', user='postgres')


@task
def pip_freeze_all():
    """
    Attempts to write requirements.txt files for all apps in apps.ini into
    their respective apps folder.
    """

    def helper(app):
        if type(app) is App:
            execute(pip_freeze, app, host=app.production)

    with settings(warn_only=True):
        for a in APPS.values():
            helper(a)

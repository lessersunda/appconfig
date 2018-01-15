# test_deployment.py

from __future__ import unicode_literals

import argparse

import pytest

from appconfig import tasks


pytestmark = pytest.mark.usefixtures('APP')


def test_deploy_distrib(mocker):
    di = mocker.patch('appconfig.tasks.deployment.system.distrib_id')
    di.return_value = 'nondistribution'
    with pytest.raises(AssertionError):
        tasks.deploy('production')

    di.return_value = 'Ubuntu'
    mocker.patch('appconfig.tasks.deployment.system.distrib_codename',
                 return_value='noncodename')
    with pytest.raises(ValueError, match='unsupported platform'):
        tasks.deploy('production')


@pytest.fixture()
def mocked_deployment(mocker):
    getpass = mocker.Mock(**{'getpass.return_value': 'password'})
    mocked = mocker.patch.multiple('appconfig.tasks.deployment',
        time=mocker.Mock(),
        getpass=getpass,
        pathlib=mocker.DEFAULT,
        prompt=mocker.Mock(return_value='app'),
        sudo=mocker.Mock(return_value='/usr/venvs/__init__.py'),
        run=mocker.Mock(return_value='{"status": "ok"}'),
        cd=mocker.DEFAULT,
        local=mocker.Mock(),
        exists=mocker.Mock(side_effect=lambda x: x.endswith('alembic.ini')),
        comment=mocker.Mock(),
        confirm=mocker.Mock(return_value=True),
        require=mocker.Mock(),
        files=mocker.Mock(),
        python=mocker.DEFAULT,
        postgres=mocker.Mock(),
        nginx=mocker.Mock(),
        service=mocker.Mock(),
        supervisor=mocker.Mock(),
        system=mocker.Mock(**{'distrib_id.return_value': 'Ubuntu',
                              'distrib_codename.return_value': 'xenial'}),
    )
    return argparse.Namespace(getpass=getpass, **mocked)


def test_deploy_public(mocker, config, mocked_deployment):
    mocker.patch('appconfig.tasks.APP', config['testapppublic'])
    tasks.deploy('production')
    mocked_deployment.getpass.getpass.assert_called_once_with(prompt=mocker.ANY)


def test_deploy(mocker, mocked_deployment):
    tasks.deploy('production')
    mocked_deployment.getpass.getpass.assert_has_calls([mocker.call(prompt=mocker.ANY)] * 2)
    assert mocked_deployment.getpass.getpass.call_count == 2
    tasks.deploy('production', with_alembic=True)
    tasks.deploy('test')
    tasks.deploy('test', with_alembic=True)

import os

from fabric.api import task
from fabtools import require, service


@task
def munin_node():
    key_path = os.path.join(os.path.dirname(__file__),
                            '../ssh_key_munin_node.pub')

    require.deb.packages(['munin-node'])
    require.users.user(
        'dlce-munin-node',
        shell='/bin/bash',
        system=True,
        ssh_public_keys=[key_path])
    service.restart('munin-node')

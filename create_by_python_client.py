from novaclient.client import Client as NovaClient
from neutronclient.v2_0.client import Client as NeutronClient
from keystoneclient.auth.identity import v2
from keystoneclient import session
from openstack import connection
import os
import click
import time
from ConfigParser import SafeConfigParser
config = SafeConfigParser()
config.read("config.ini")
conn = connection.Connection(auth_url=os.environ["OS_AUTH_URL"],
                             project_name=os.environ["OS_TENANT_NAME"],
                             username=os.environ["OS_USERNAME"],
                             password=os.environ["OS_PASSWORD"])


auth = v2.Password(auth_url=os.environ["OS_AUTH_URL"],
                   username=os.environ["OS_USERNAME"],
                   password=os.environ["OS_PASSWORD"],
                   tenant_name=os.environ["OS_TENANT_NAME"])
nova_client = NovaClient(2, session=session.Session(auth=auth))
neutron_client = NeutronClient(session=session.Session(auth=auth))


def _wait_for_status(server, status="ACTIVE", retry=20, wait=10):
    for i in range(retry):
        if server.status == status:
            return server
        time.sleep(wait)
        server = nova_client.servers.get(server.id)
    raise RuntimeError("wait_for_status check retry count over")

@click.command()
@click.option('--external_network_name', prompt='Input external network name')
@click.option('--external_network_dns_server_ip_address', prompt='Input dns server ip address')
@click.option('--cidr_can_connect_to_server', prompt='Input Cidr can connect to server by using ssh')
@click.option('--server_image_name', prompt='Input Base image name for server')
@click.option('--server_flavor_name', prompt='Input Flavor name for server')
@click.option('--server_count', prompt='Input server count')
def create(external_network_name,
           external_network_dns_server_ip_address,
           cidr_can_connect_to_server,
           server_image_name,
           server_flavor_name,
           server_count):
    """
    This program requires public network and base Linux image
    ie:
    external_network_name = "publicNW"
    external_network_dns_server_ip_address = "192.168.100.254"
    cidr_can_connect_to_server = "192.168.100.0/24"
    server_image_name = "centos-base"
    server_flavor_name = "m1.medium"
    server_count = "3"
    """
    external_network = neutron_client.list_networks(name=external_network_name)["networks"][0]
    click.echo("create router         : %s" % config.defaults().get("router_name"))
    router_args = {
        "router": {
            "name": config.defaults().get("router_name"),
            "external_gateway_info": {"network_id": external_network["id"]}
        }
    }
    app_router = neutron_client.create_router(router_args)["router"]
    click.echo("create network        : %s" % config.defaults().get("network_name"))
    network_args = {
        "network": {
            "name": config.defaults().get("network_name"),
        }
    }
    network = neutron_client.create_network(network_args)["network"]
    click.echo("create subnet         : %s" % config.defaults().get("subnet_name"))
    subnet_args = {
        "subnet": {
            "name": config.defaults().get("subnet_name"),
            "network_id": network["id"],
            "ip_version": "4",
            "dns_nameservers": [external_network_dns_server_ip_address],
            "cidr": config.defaults().get("subnet_cidr")
        }
    }
    subnet = neutron_client.create_subnet(subnet_args)["subnet"]
    click.echo("add router interface...")
    router_interface_args = {
        "subnet_id": subnet["id"]
    }
    neutron_client.add_interface_router(app_router["id"], router_interface_args)

    click.echo("create security_group : %s" % config.defaults().get("security_group_name"))
    security_group_args = {
        "security_group": {
            "name": config.defaults().get("security_group_name"),
            "description": config.defaults().get("security_group_name")
        }
    }
    security_group = neutron_client.create_security_group(security_group_args)["security_group"]
    all_tcp_from_local = {
        "security_group_rule": {
            'direction': 'ingress',
            'remote_ip_prefix': subnet["cidr"],
            'protocol': "tcp",
            'port_range_min': "1",
            'port_range_max': "65535",
            'security_group_id': security_group["id"],
            'ethertype': 'IPv4'
        }
    }
    all_icmp_from_local = {
        "security_group_rule": {
            'direction': 'ingress',
            'remote_ip_prefix': subnet["cidr"],
            'protocol': 'icmp',
            'port_range_min': None,
            'port_range_max': None,
            'security_group_id':  security_group["id"],
            'ethertype': 'IPv4'
        }
    }
    ssh_from_external = {
        "security_group_rule": {
            'direction': 'ingress',
            'remote_ip_prefix': cidr_can_connect_to_server,
            'protocol': "tcp",
            'port_range_min': "22",
            'port_range_max': "22",
            'security_group_id':  security_group["id"],
            'ethertype': 'IPv4'
        }
    }
    neutron_client.create_security_group_rule(all_tcp_from_local)
    neutron_client.create_security_group_rule(all_icmp_from_local)
    neutron_client.create_security_group_rule(ssh_from_external)

    image = nova_client.images.find(name=server_image_name)

    flavor = nova_client.flavors.find(name=server_flavor_name)

    click.echo("create keypair        : %s" % config.defaults().get("keypair_name"))
    keypair = nova_client.keypairs.create(config.defaults().get("keypair_name"))
    click.echo("create keypair file   : %s" % config.defaults().get("keypair_file"))
    with open(config.defaults().get("keypair_file"), "w") as f:
        f.write(keypair.private_key)
    os.chmod(config.defaults().get("keypair_file"), 0600)

    with open(config.defaults().get("cloud_init"), 'r') as f:
        user_data = f.read()

    for i in range(int(server_count)):
        server = nova_client.servers.create(config.defaults().get("server_prefix") + str(i),
                                            image.id,
                                            flavor.id,
                                            key_name=keypair.name,
                                            meta={"foo": "bar"},
                                            userdata=user_data,
                                            files={config.defaults().get("keypair_file"): keypair.private_key},
                                            security_groups=[security_group["name"]],
                                            nics=[{"net-id": network["id"]}])
        server = _wait_for_status(server)

        server_fixed_ip_address = server.networks[config.defaults().get("network_name")][0]
        network_args = {
            "floatingip": {
                "floating_network_id": external_network["id"]
            }
        }
        floating_ip = neutron_client.create_floatingip(network_args)["floatingip"]
        server.add_floating_ip(floating_ip["floating_ip_address"])

        click.echo("")
        click.echo(("id of " + server.name).ljust(30) + ': %s' % server.id)
        click.echo(("fixed_ip of " + server.name).ljust(30) + ': %s' % server_fixed_ip_address)
        click.echo(("floating_ip of " + server.name).ljust(30) + ': %s' % floating_ip["floating_ip_address"])

    click.echo("")
    click.echo("...Finished!")
    click.echo("You can connect to server by using following command")
    click.echo("ssh -i %s user@server" % config.defaults().get("keypair_file"))


if __name__ == '__main__':
    create()

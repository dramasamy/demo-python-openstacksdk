from novaclient.client import Client as NovaClient
from neutronclient.v2_0.client import Client as NeutronClient
from keystoneclient.auth.identity import v2
from keystoneclient import session
import os
from ConfigParser import SafeConfigParser

config = SafeConfigParser()
config.read("config.ini")

auth = v2.Password(auth_url=os.environ["OS_AUTH_URL"],
                   username=os.environ["OS_USERNAME"],
                   password=os.environ["OS_PASSWORD"],
                   tenant_name=os.environ["OS_TENANT_NAME"])
nova_client = NovaClient(2, session=session.Session(auth=auth))
neutron_client = NeutronClient(session=session.Session(auth=auth))


def _delete_servers():
    for server in nova_client.servers.list():
        floating_ips = nova_client.floating_ips.list()
        if server.name.startswith(config.defaults().get("server_prefix")) and \
            raw_input("Input 'y' if you want to delete this server[name=%s, id=%s]: " % (
                server.name, server.id)) == "y":
            for server_ip in server.networks[config.defaults().get("network_name")]:
                for floating_ip in floating_ips:
                    if floating_ip.ip == server_ip:
                        print("deleting floating_ip    : " + floating_ip.ip)
                        floating_ip.delete()
            if hasattr(server, "security_groups"):
                for security_group in server.security_groups:
                    server.remove_security_group(security_group["name"])
            server.delete()


def _delete_network():
    router = neutron_client.list_routers(name=config.defaults().get("router_name"))["routers"][0]
    subnet = neutron_client.list_subnets(name=config.defaults().get("subnet_name"))["subnets"][0]
    network = neutron_client.list_networks(name=config.defaults().get("network_name"))["networks"][0]

    if router and subnet:
        router_interface_args = {
            "subnet_id": subnet["id"]
        }
        neutron_client.remove_interface_router(router["id"], router_interface_args)
    if network:
        print("deleting subnet         : " + config.defaults().get("network_name"))
        print("deleting network        : " + config.defaults().get("network_name"))
        neutron_client.delete_network(network["id"])
    if router:
        print("deleting router         : " + config.defaults().get("router_name"))
        neutron_client.delete_router(router["id"])


def _delete_security_group():
    print("deleting security_group : " + config.defaults().get("security_group_name"))
    security_group = nova_client.security_groups.list({"name": config.defaults().get("security_group_name")})[0]
    if security_group:
        security_group.delete()


def _delete_keypair():
    print("deleting keypair        : " + config.defaults().get("keypair_name"))
    keypair = nova_client.keypairs.get(config.defaults().get("keypair_name"))
    if keypair:
        keypair.delete()


def delete():
    _delete_servers()
    _delete_security_group()
    _delete_keypair()
    _delete_network()
    print("...Finished!")


if __name__ == "__main__":
    delete()
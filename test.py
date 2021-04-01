#!/usr/bin/env python3
import os
import yaml
import subprocess
import downloader as down
import libvirt
from jinja2 import Template
import cm_client
from cm_client.rest import ApiException
from pprint import pprint

config = yaml.load(open("config.yaml"), Loader=yaml.FullLoader)
configuration = cm_client.Configuration()
api_url = 'http://192.168.122.11:7180/api/v41'
configuration.username = 'admin'
configuration.password = 'admin'
api_client = cm_client.ApiClient(api_url)
CLUSTER_NAME = 'test-cluster'

try:
    api_cm = cm_client.ClouderaManagerResourceApi(api_client)
    api_clusters = cm_client.ClustersResourceApi(api_client)




    #api_response = api_cm.begin_trial()
    #pprint(api_response)

    api_response = api_clusters.create_clusters(body=cm_client.ApiClusterList(items=[{'name': CLUSTER_NAME,
    'fullVersion': '7.1.4',
    'clusterType': 'BASE_CLUSTER'}]))
    #pprint(api_response)



api_clusters.g
    api_response = api_clusters.add_hosts(
        cluster_name=CLUSTER_NAME,
        body=cm_client.ApiHostRefList(items=[{'hostname': 'cdh7-data-001.cdh7.local'}]))
    pprint(api_response)

except ApiException as e:
    print("Exception when calling ClustersResourceApi->create_clusters: %s\n" % e)


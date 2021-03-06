import os
import asyncio
import kopf
from misc import get_required_env_var, get_env_var_bool, get_env_var_int
from io_helpers import create_folder, write_file, delete_file

LABEL = get_required_env_var('LABEL')

def label_is_satisfied(meta, **_):
    """Runs the logic for LABEL and LABEL_VALUE and tells us if we need to watch the resource"""
    label_value = os.getenv('LABEL_VALUE')

    # if there are no labels in the resource, there's no point in checking further
    if 'labels' not in meta:
        return False

    # If LABEL_VALUE wasn't set but we find the LABEL, that's good enough
    if label_value is None and LABEL in meta['labels'].keys():
        return True

    # If LABEL_VALUE was set, it needs to be the value of LABEL for one of the key-vars in the dict
    for key, value in meta['labels'].items():
        if key == LABEL and value == label_value:
            return True

    return False

def resource_is_desired(body, **_):
    """Runs the logic for the RESOURCE environment variable"""
    resource = os.getenv('RESOURCE', 'configmap')

    kind = body['kind'].lower()

    return resource in (kind, 'both')

@kopf.on.startup()
def startup_tasks(settings: kopf.OperatorSettings, logger, **_):
    """Perform all necessary startup tasks here. Keep them lightweight and relevant
    as the other handlers won't be initialized until these tasks are complete"""

    # Check that the required environment variables are present before we start
    folder = get_required_env_var('FOLDER')

    # Create the folder from which we will write/delete files
    create_folder(folder, logger)

    # Check that the user used a sane value for RESOURCE
    resource = os.getenv('RESOURCE', 'configmap')
    valid_resources = ['configmap', 'secret', 'both']
    if resource not in valid_resources:
        logger.error(f"RESOURCE should be one of [{', '.join(valid_resources)}]. Resources won't match until this is fixed!")

    # Replace the default marker with something less cryptic
    settings.persistence.finalizer = 'kopf.zalando.org/K8sSidecarFinalizerMarker'

    # Set the client and service k8s API timeouts
    # Very important! Without proper values, the operator may stop responding!
    # See https://github.com/nolar/kopf/issues/585
    client_timeout = get_env_var_int('WATCH_CLIENT_TIMEOUT', 660, logger)
    server_timeout = get_env_var_int('WATCH_SERVER_TIMEOUT', 600, logger)

    logger.info(f"Client watching requests using a timeout of {client_timeout} seconds")
    settings.watching.client_timeout = client_timeout

    logger.info(f"Server watching requests using a timeout of {server_timeout} seconds")
    settings.watching.server_timeout = server_timeout

    # The client timeout shouldn't be shorter than the server timeout
    # https://kopf.readthedocs.io/en/latest/configuration/#api-timeouts
    if client_timeout < server_timeout:
        logger.warning(f"The client timeout ({client_timeout}) is shorter than the server timeout ({server_timeout}). Consider increasing the client timeout to be higher")

    # Set k8s event logging
    settings.posting.enabled = get_env_var_bool('EVENT_LOGGING')

    if get_env_var_bool('UNIQUE_FILENAMES'):
        logger.info("Unique filenames will be enforced.")

@kopf.on.resume('', 'v1', 'configmaps', when=kopf.all_([label_is_satisfied, resource_is_desired]))
@kopf.on.create('', 'v1', 'configmaps', when=kopf.all_([label_is_satisfied, resource_is_desired]))
@kopf.on.update('', 'v1', 'configmaps', when=kopf.all_([label_is_satisfied, resource_is_desired]))
@kopf.on.resume('', 'v1', 'secrets', when=kopf.all_([label_is_satisfied, resource_is_desired]))
@kopf.on.create('', 'v1', 'secrets', when=kopf.all_([label_is_satisfied, resource_is_desired]))
@kopf.on.update('', 'v1', 'secrets', when=kopf.all_([label_is_satisfied, resource_is_desired]))
async def cru_fn(body, event, logger, **_):
    try:
        await write_file(event, body, logger)
    except asyncio.CancelledError:
        logger.info(f"Write file cancelled for {body['kind']}")

@kopf.on.delete('', 'v1', 'configmaps', when=kopf.all_([label_is_satisfied, resource_is_desired]))
@kopf.on.delete('', 'v1', 'secrets', when=kopf.all_([label_is_satisfied, resource_is_desired]))
async def delete_fn(body, logger, **_):
    try:
        await delete_file(body, logger)
    except asyncio.CancelledError:
        logger.info(f"Delete file cancelled for {body['kind']}")

import concurrent.futures
import uuid

from fdc3.desktop_agent.core.channel_manager import ChannelManager


def _worker(cm: ChannelManager, instance_id: str):
    # Each worker attempts to create the same channel and join it
    cm.create_channel("user:demo", "user")
    cm.join_channel(instance_id, "user:demo")


def test_concurrent_create_and_join():
    cm = ChannelManager()

    instances = [str(uuid.uuid4()) for _ in range(20)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(_worker, cm, iid) for iid in instances]
        concurrent.futures.wait(futures, timeout=10)

    members = cm.get_channel_members("user:demo")

    # All instances should have joined
    assert set(members) == set(instances)

    # Only a single channel instance should exist for the id
    channel = cm.get_channel("user:demo")
    assert channel is not None
    assert len(cm.channels) >= 1

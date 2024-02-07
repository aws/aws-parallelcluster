EXTERNAL_STORAGE_KEYS = ["VolumeId", "FileSystemId", "FileCacheId"]


class SharedStorageChangeInfo:
    """
    Capture relevant information about a change to the shared storage.

    Relevant info are:
      1. the requested action: mount or unmount.
      2. the storage type: EFS, FSx.
      3. the storage ownership (external or managed).
    """

    def __init__(self, change):
        old_value = change.old_value
        new_value = change.new_value

        is_storage_list_change = change.is_list and change.key == "SharedStorage"
        storage_item = new_value if new_value is not None else old_value

        # Storage Action
        self.is_mount = is_storage_list_change and old_value is None and new_value is not None
        self.is_unmount = is_storage_list_change and old_value is not None and new_value is None

        self.storage_type = storage_item.get("StorageType")
        self.storage_settings = storage_item.get(f"{self.storage_type}Settings", {})

        # Storage Ownership
        self.is_external = any(key in self.storage_settings for key in EXTERNAL_STORAGE_KEYS)

        # Storage Type
        self.storage_type = storage_item.get("StorageType")

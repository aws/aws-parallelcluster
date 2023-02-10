from enum import Enum


class StorageType(Enum):
    """Types of storage resources."""

    STORAGE_EBS = "EBS"
    STORAGE_EFS = "EFS"
    STORAGE_FSX = "FSX"

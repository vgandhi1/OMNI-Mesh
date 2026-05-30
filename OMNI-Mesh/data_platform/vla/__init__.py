"""Vision-Language-Action (VLA) training flywheel for the ROBOTICS profile.

CV feature extraction, WebDataset shard writing, and closed-loop inference logging.
All heavy ML deps (torchvision, webdataset, ray) are optional and lazily imported
with graceful fallbacks, so the flywheel runs even without ``requirements-ml.txt``.
"""

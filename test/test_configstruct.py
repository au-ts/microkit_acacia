# Copyright 2026, UNSW
# SPDX-License-Identifier: BSD-2-Clause

from pathlib import Path

from acacia import ConfigStruct, ProtectionDomain, Subsystem, System
from acacia.arch import riscv64


def test_prefill_creates_client_regions_and_blobs(tmp_path):
    class PrefillSubsystem(Subsystem):
        def __init__(self, sdf, configs):
            super().__init__(sdf, "prefill")
            self.configs = configs

        def generate_config_structs(self):
            return self.configs

    elf = Path("examples/dummy_configstruct_build/i2c_driver.elf")
    sdf = System(riscv64, paddr_top=0x100000000)
    names = ("client1", "client2", "client3")
    configs = []
    for name in names:
        pd = ProtectionDomain(sdf, name, str(elf), priority=1)
        if name == "client2":
            config = ConfigStruct(
                {},
                type_name="device_resources_t",
                target_file=elf,
                empty=True,
                prefill_pd=pd,
                prefill_symbol="device_resources",
                build_dir=tmp_path,
            )
        else:
            config = ConfigStruct(
                {}, type_name="device_resources_t", target_file=elf, empty=True
            )
            config.reserve_prefill_mr(
                pd,
                "device_resources",
                build_dir=tmp_path,
                perms="rw" if name == "client3" else "r",
            )
        configs.append(config)

    PrefillSubsystem(sdf, configs)
    sdf.make_config_structs(tmp_path)
    root = sdf.render()
    assert len(root.findall("memory_region")) == len(names)
    # Validate that the expected MR exists, for each config blob.
    for name in names:
        region_name = f"{name}_device_resources"
        region = root.find(f"memory_region[@name='{region_name}']")
        assert region is not None
        assert int(region.get("size"), 16) == 0x1000

        mapping = root.find(
            f"protection_domain[@name='{name}']/map[@mr='{region_name}']"
        )
        assert mapping is not None
        if region_name == "client3_device_resources":
            assert mapping.get("perms") == "rw"
        else:
            assert mapping.get("perms") == "r"
        assert mapping.get("setvar_vaddr") == "device_resources"
        assert int(mapping.get("vaddr"), 16) % 0x1000 == 0
        blob_path = tmp_path / f"{region_name}.data"
        assert region.get("prefill_path") == str(blob_path)
        assert blob_path.is_file()
        assert blob_path.read_bytes() == bytes(0x648)

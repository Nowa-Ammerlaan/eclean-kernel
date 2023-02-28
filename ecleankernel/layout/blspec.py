# vim:fileencoding=utf-8
# (c) 2020-2023 Michał Górny <mgorny@gentoo.org>
# Released under the terms of the 2-clause BSD license.

import logging
import os
import typing

from pathlib import Path

from ecleankernel.file import (
    KernelFileType,
    GenericFile,
    KernelImage,
    UnrecognizedKernelError,
    EmptyDirectory,
    )
from ecleankernel.kernel import Kernel
from ecleankernel.layout import LayoutNotFound
from ecleankernel.layout.moduledir import ModuleDirLayout


class BlSpecLayout(ModuleDirLayout):
    """
    A layout implementing Bootloader Specification

    A Bootloader Spec layout, i.e. using /boot/[EFI/]<machine-id>
    directories.
    """

    name = 'blspec'
    potential_dirs = ('boot/EFI', 'boot/efi', 'boot', 'efi')

    name_map = {
        'initrd': KernelFileType.INITRAMFS,
        'linux': KernelFileType.KERNEL,
    }

    def __init__(self,
                 root: Path
                 ) -> None:
        super().__init__(root)
        # TODO: according to bootctl(1), we should fall back to IMAGE_ID=
        # and then ID= from os-release
        for path in ("etc/kernel/entry-token", "etc/machine-id"):
            try:
                with open(root / path) as f:
                    kernel_id = f.read().strip()
                break
            except FileNotFoundError:
                pass
        else:
            raise LayoutNotFound("/etc/machine-id not found")

        for d in self.potential_dirs:
            self.bootdir = root / d / kernel_id
            if self.bootdir.is_dir():
                return
        else:
            raise LayoutNotFound(f"/boot/[EFI/]{kernel_id} not found")

    def find_kernels(self,
                     exclusions: typing.Container[KernelFileType] = [],
                     ) -> typing.List[Kernel]:
        # this would wreak havok all around the place
        assert KernelFileType.KERNEL not in exclusions

        # collect all module directories first
        module_dict = self.get_module_dict(
            exclusions=exclusions,
            module_directory=self.root / 'lib/modules')

        # collect from /boot
        kernels: typing.Dict[str, Kernel] = {}
        for ver in os.listdir(self.bootdir):
            if ver.startswith('.'):
                continue
            dir_path = self.bootdir / ver
            if dir_path.is_symlink() or not dir_path.is_dir():
                continue

            k = Kernel(ver)
            for fn in os.listdir(dir_path):
                if fn.startswith('.'):
                    continue
                path = dir_path / fn
                ftype = self.name_map.get(fn, KernelFileType.MISC)
                fobj = GenericFile(path, ftype)
                if ftype == KernelFileType.KERNEL:
                    try:
                        kobj = KernelImage(path)
                    except UnrecognizedKernelError as err:
                        logging.debug(
                            f"Unrecognized potential kernel image: {err}")
                    else:
                        # associate the module directory
                        k.all_files.extend(
                            module_dict.get(kobj.internal_version, []))
                        fobj = kobj
                if ftype not in exclusions:
                    k.all_files.append(fobj)
            k.all_files.append(EmptyDirectory(dir_path))
            kernels[ver] = k

        # merge unassociated modules into kernel groups
        for mkv, fobjs in module_dict.items():
            if any(mkv == k.real_kv for k in kernels.values()):
                continue
            kernels.setdefault(mkv, Kernel(mkv)).all_files.extend(fobjs)

        return list(kernels.values())

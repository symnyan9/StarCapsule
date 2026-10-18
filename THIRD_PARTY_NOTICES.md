# Third-party notices

StarCapsule's original application code is MIT licensed. The following upstream components retain their own licenses and notices.

## Viewer and source distribution

The application bundles **Three.js r146** and **OrbitControls r146** under the MIT license. Their original license and download URL/SHA256 records are retained in `src/cfd_review/assets/vendor/`. Generated HTML embeds the corresponding code with its license notice. The source package and wheel do not bundle a Python interpreter or native STAR libraries.

Python standard-library modules provide the application's Python runtime dependencies. Playwright is an optional development/checking dependency; it is unnecessary for using the desktop application or opening exported reports.

## Optional Windows runtime distribution

The complete Windows x64 package includes an unmodified **CPython 3.14.2** runtime and its native dependencies. Python's `runtime/LICENSE.txt`, installed library notices and the additional license files below travel with that package. StarCapsule adds its own application in `site-packages`; it does not modify the interpreter or the dependency binaries. Packaging excludes installed third-party `site-packages` and compiled Python caches, and relocates the selected interpreter, standard library, DLLs and Tcl/Tk files into the application folder.

| Component | Retained notice |
| --- | --- |
| CPython 3.14.2 and incorporated software | [Python license](licenses/CPYTHON_LICENSE.txt), [incorporated-software notices](licenses/CPYTHON_THIRD_PARTY_LICENSES.rst), and the runtime's original aggregate `LICENSE.txt` |
| Microsoft code in the Windows Python build | [CPython Windows binary conditions](licenses/MICROSOFT_RUNTIME_NOTICE.txt); these apply to Microsoft's distributable code, separately from StarCapsule's MIT code |
| OpenSSL 3.0.18 | [Apache License 2.0](licenses/OPENSSL_LICENSE.txt) and [upstream copyright](licenses/OPENSSL_COPYRIGHT.txt) |
| zlib-ng 2.2.4 | [zlib license](licenses/ZLIB_NG_LICENSE.md) |
| Zstandard 1.5.7 | [BSD license](licenses/ZSTD_LICENSE.txt) |
| Tcl/Tk 8.6.15 | [Tcl terms](licenses/TCL_LICENSE.txt) and [Tk terms](licenses/TK_LICENSE.txt) |
| SQLite 3.50.4 | [Source public-domain dedication](licenses/SQLITE_PUBLIC_DOMAIN.txt) |
| liblzma from XZ Utils 5.2.5 | [Upstream licensing summary](licenses/LIBLZMA_LICENSING.txt); liblzma's source is public domain, with Windows binary conditions retained separately |

[License sources and SHA256 records](licenses/SOURCES.json) identify the official, versioned upstream files and the CPython Windows dependency profile. These records distinguish observed runtime versions from versions inferred from that build profile. Retain the package's complete license directory, runtime notices and any embedded dependency-wheel licenses when redistributing it.

## STAR-CCM+

STAR-CCM+ is separately installed commercial software by Siemens. StarCapsule distributes no STAR application, Java libraries, solver or license. Export macros run inside the user's own compatible and licensed STAR installation. Product names identify interoperability; they do not imply affiliation or endorsement.

## 中文说明

StarCapsule 原创代码采用 MIT 许可；Three.js、OrbitControls 及完整 Windows 包内的 Python 和原生依赖分别保留各自许可。完整 Windows 包附带 CPython 3.14.2，公开源码和 wheel 本身不包含解释器。重新分发完整包时，请保留 `licenses`、运行时原始许可及内含依赖的许可文件。各文件的官方来源、版本依据及 SHA256 见 `licenses/SOURCES.json`。

STAR-CCM+ 由使用者另行安装并取得有效许可，本项目不分发 STAR 软件或许可，也不表示获得其厂商背书。

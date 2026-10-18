# Install StarCapsule Studio

[简体中文](INSTALL.zh-CN.md) · [Review guide](REVIEW.md)

## Complete Windows x64 package

1. Download the `StarCapsule-Studio-0.3.0-Windows-x64.zip` release asset and extract the **entire** archive.
2. Double-click **Install.cmd**. The included Python/Tk runtime requires no separate Python installation or administrator account.
3. Open **StarCapsule Studio** from the desktop shortcut. You can also run **Launch.cmd** directly in the extracted folder for portable use.

The installer defaults to English. To use Chinese installation messages, open PowerShell in the extracted folder and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -Language zh-CN
```

The application and new reports default to English; select **简体中文** in their headers to switch. The desktop remembers the local choice; saved HTML and project JSON retain their language independently. Source names and user text remain unchanged.

## Source checkout or Python wheel

Python 3.10+ is required; the desktop interface also needs Tkinter. From a source checkout, run `python run.py gui` or use **Open Studio.cmd**. For a wheel, install offline:

```powershell
python -m pip install --no-index starcapsule_studio-0.3.0-py3-none-any.whl
starcapsule-gui
```

## Export and viewing prerequisites

Reading `.sim` requires your own compatible, licensed STAR-CCM+ installation. The app launches its export process in the background; it does not distribute STAR or its license. The current native API profile is 19.02.009; other versions need separate validation.

Viewing the exported HTML needs only a desktop browser with WebGL and native gzip decompression. The selected data and viewer are embedded locally. A STAR network-license arrangement can still require its license server during export. See [validation](VALIDATION.md) for tested environments and remaining limits.

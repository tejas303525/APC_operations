# NAS Storage Setup — APC Operations

This guide explains how to configure the NAS file storage for COA PDFs and Security checklists.

---

## How It Works

The system saves generated PDF documents to a network-attached storage (NAS) share. The NAS must be **mounted on the Linux server** as a local folder. APC Operations writes files using the server's filesystem — it does not connect directly to the NAS over SMB from Python.

Files saved:

| Document | NAS Path |
|----------|----------|
| COA PDF | `{NAS Base Path}/QC/COA/{YYYY}/{Customer}/{JobOrder}/{COA}_{Batch}.pdf` |
| Security Checklist | `{NAS Base Path}/QC/Checklists/{YYYY}/{InspectionName}_QC-Checklist.pdf` |

The file path is stored in:
- `APC COA.nas_path`
- `APC Batch.nas_path`
- `Security Inspection.checklist_nas_path` (if field exists)

---

## Step 1 — Mount the NAS Share on the Server

The Frappe bench runs on Linux. Mount the NAS share as a local folder.

### Install CIFS utilities (if not already installed)

```bash
sudo apt-get install cifs-utils
```

### Create a mount point

```bash
sudo mkdir -p /mnt/nas/apc-operations
```

### Mount the share

```bash
sudo mount -t cifs //NAS_IP/SHARE_NAME /mnt/nas/apc-operations \
  -o username=NAS_USERNAME,password=NAS_PASSWORD,uid=frappe,gid=frappe,iocharset=utf8
```

Replace:
- `NAS_IP` — IP address of your NAS device (e.g., `192.168.1.50`)
- `SHARE_NAME` — share name on the NAS (e.g., `APC-Operations`)
- `NAS_USERNAME` — NAS user with read/write access
- `NAS_PASSWORD` — NAS user password

### Test the mount

```bash
ls /mnt/nas/apc-operations
```

You should see the NAS share contents.

---

## Step 2 — Make the Mount Permanent

Edit `/etc/fstab` so the share auto-mounts on reboot.

```bash
sudo nano /etc/fstab
```

Add this line at the bottom:

```
//NAS_IP/SHARE_NAME  /mnt/nas/apc-operations  cifs  username=NAS_USERNAME,password=NAS_PASSWORD,uid=frappe,gid=frappe,_netdev,iocharset=utf8  0  0
```

> **Tip:** For security, store credentials in a separate file instead of putting them in fstab directly.
>
> ```bash
> sudo nano /etc/nas-credentials
> ```
>
> Contents:
> ```
> username=NAS_USERNAME
> password=NAS_PASSWORD
> ```
>
> ```bash
> sudo chmod 600 /etc/nas-credentials
> ```
>
> Then in fstab use: `credentials=/etc/nas-credentials` instead of `username=...`

---

## Step 3 — Verify Frappe Can Write to the Mount

The Frappe/bench process runs as the `frappe` Linux user. Confirm it has write access:

```bash
sudo -u frappe touch /mnt/nas/apc-operations/test-write.txt
sudo -u frappe rm /mnt/nas/apc-operations/test-write.txt
```

If both commands succeed without errors, the service will be able to save files.

If you get a "Permission denied" error, check that:
- The `uid=frappe,gid=frappe` options are set in the mount command
- The NAS share permissions allow the NAS user to write files

---

## Step 4 — Configure in the APC Operations UI

1. Log in as **System Manager**
2. Open: **APC NAS Settings**
   - Search bar → type `APC NAS Settings`
   - Or navigate directly to `/app/apc-nas-settings`

3. Fill in the form:

| Field | Value | Notes |
|-------|-------|-------|
| **Enable NAS Storage** | ✅ Checked | Must be enabled for saves to run |
| **NAS Base Path** | `/mnt/nas/apc-operations` | The Linux mount point — this is the only field the code uses |
| **NAS Server / Host** | `192.168.1.50` | Reference only — not used by the code |
| **Share Name** | `APC-Operations` | Reference only |
| **Username** | `NAS_USERNAME` | Reference only |
| **Password** | `NAS_PASSWORD` | Reference only |

4. Click **Save**

---

## Step 5 — Verify the Configuration

In the Frappe console, run a quick check:

```bash
bench --site apc.local console
```

```python
from apc_operations.services.nas_service import _nas_is_enabled, get_nas_path

# Should print True if enabled and base path is set
print(_nas_is_enabled())

# Should print the full path that a COA would be saved to
print(get_nas_path(["QC", "COA", "2026", "CustomerA", "JO-2026-00001"], "COA-001_BATCH-001.pdf"))
```

---

## Behaviour When NAS Is Unavailable

The NAS save is **non-blocking**. If the NAS is unreachable or the write fails:

- The error is logged in Frappe's error log (visible under **Error Log** in the UI)
- COA approval and QC clearance are **not blocked**
- A **nightly scheduled job** automatically retries all approved COAs and completed inspections that have no `nas_path` recorded

To manually retry NAS saves:

```bash
bench --site apc.local execute apc_operations.services.nas_service.retry_failed_nas_saves
```

---

## NAS Folder Structure Created Automatically

```
/mnt/nas/apc-operations/
└── QC/
    ├── COA/
    │   └── 2026/
    │       └── CustomerName/
    │           └── JO-2026-00001/
    │               └── COA-2026-00001_BATCH-2026-00001.pdf
    └── Checklists/
        └── 2026/
            └── SEC-INS-2026-00001_QC-Checklist.pdf
```

Folders are created automatically by the service if they do not exist.

---

## Troubleshooting

| Problem | Check |
|---------|-------|
| Files not saving | Is NAS mounted? Run `df -h \| grep nas` |
| Permission denied | Run `sudo -u frappe touch /mnt/nas/apc-operations/test.txt` |
| Mount lost after reboot | Check `/etc/fstab` has the `_netdev` flag |
| `nas_path` empty on COA | Check Error Log in Frappe for "NAS COA Save" entries |
| `_nas_is_enabled()` returns False | Open APC NAS Settings and confirm **Enable NAS Storage** is checked and **NAS Base Path** is filled |

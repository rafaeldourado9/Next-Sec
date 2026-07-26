"""Script CLI para criar câmeras de teste em lote."""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

CAMERAS = [
    # RTSP - Dahua
    {"name": "Dahua-Ext-01", "rtsp": "rtsp://admin:Camerite123@45.236.226.70:6044/cam/realmonitor?channel=1&subtype=0", "proto": "rtsp_pull", "mfr": "generic"},
    {"name": "Dahua-Ext-02", "rtsp": "rtsp://admin:Camerite123@45.236.226.70:6045/cam/realmonitor?channel=1&subtype=0", "proto": "rtsp_pull", "mfr": "generic"},
    {"name": "Dahua-Ext-03", "rtsp": "rtsp://admin:Camerite123@45.236.226.71:6046/cam/realmonitor?channel=1&subtype=0", "proto": "rtsp_pull", "mfr": "generic"},
    {"name": "Dahua-Ext-04", "rtsp": "rtsp://admin:Camerite123@45.236.226.71:6047/cam/realmonitor?channel=1&subtype=0", "proto": "rtsp_pull", "mfr": "generic"},
    {"name": "Dahua-Ext-05", "rtsp": "rtsp://admin:Camerite123@45.236.226.72:6048/cam/realmonitor?channel=1&subtype=0", "proto": "rtsp_pull", "mfr": "generic"},
    {"name": "Dahua-Ext-06", "rtsp": "rtsp://admin:Camerite123@45.236.226.72:6049/cam/realmonitor?channel=1&subtype=0", "proto": "rtsp_pull", "mfr": "generic"},
    # RTMP - Intelbras
    {"name": "Intelbras-RTMP-01", "rtsp": None, "proto": "rtmp_push", "mfr": "intelbras", "key": "7KOM27155085F.stream"},
    {"name": "Intelbras-RTMP-02", "rtsp": None, "proto": "rtmp_push", "mfr": "intelbras", "key": "7KOM2715585AK.stream"},
    {"name": "Intelbras-RTMP-03", "rtsp": None, "proto": "rtmp_push", "mfr": "intelbras", "key": "7KOM2715805PF.stream"},
    # RTSP - Hikvision
    {"name": "Hik-Int-01", "rtsp": "rtsp://admin:Camerite@170.84.217.71:608/h264/ch1/main/av_stream", "proto": "rtsp_pull", "mfr": "hikvision"},
    {"name": "Hik-Int-02", "rtsp": "rtsp://admin:Camerite@170.84.217.83:608/h264/ch1/main/av_stream", "proto": "rtsp_pull", "mfr": "hikvision"},
    {"name": "Hik-Int-03", "rtsp": "rtsp://admin:Camerite@170.84.217.84:603/h264/ch1/main/av_stream", "proto": "rtsp_pull", "mfr": "hikvision"},
    {"name": "Hik-Int-04", "rtsp": "rtsp://admin:Camerite@186.226.193.111:600/h264/ch1/main/av_stream", "proto": "rtsp_pull", "mfr": "hikvision"},
    {"name": "Hik-Int-05", "rtsp": "rtsp://admin:Camerite@186.226.193.111:601/h264/ch1/main/av_stream", "proto": "rtsp_pull", "mfr": "hikvision"},
    # RTMP - Hik Pro Connect
    {"name": "HikPro-RTMP-01", "rtsp": None, "proto": "rtmp_push", "mfr": "hikvision", "key": "FC2487237.stream"},
    {"name": "HikPro-RTMP-02", "rtsp": None, "proto": "rtmp_push", "mfr": "hikvision", "key": "FC2487838.stream"},
    {"name": "HikPro-RTMP-03", "rtsp": None, "proto": "rtmp_push", "mfr": "hikvision", "key": "FC2487653.stream"},
]


async def _run() -> None:
    from vms.cameras.domain import CameraManufacturer, StreamProtocol
    from vms.cameras.models import CameraModel
    from vms.cameras.mediamtx import MediaMTXClient
    from vms.infrastructure.database import close_db, create_engine, get_db_context, init_db
    from vms.infrastructure.security import hash_password
    from vms.iam.models import TenantModel, UserModel
    import secrets

    engine = create_engine()
    init_db(engine)
    mt = MediaMTXClient()

    async with get_db_context() as session:
        from sqlalchemy import select

        # Get or create tenant
        tenant = await session.scalar(select(TenantModel).where(TenantModel.slug == "minha-empresa"))
        if not tenant:
            print("ERRO: Tenant 'minha-empresa' não encontrado. Rode seed.bat primeiro.")
            sys.exit(1)

        tenant_id = tenant.id

        # Create cameras
        created = 0
        for cam_data in CAMERAS:
            import secrets
            stream_key = cam_data.get("key") or f"vms_{secrets.token_urlsafe(24)}"

            camera = CameraModel(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                name=cam_data["name"],
                manufacturer=cam_data["mfr"],
                stream_protocol=cam_data["proto"],
                rtsp_url=cam_data.get("rtsp"),
                rtmp_stream_key=stream_key if cam_data["proto"] == "rtmp_push" else None,
                retention_days=7,
                is_active=True,
                is_online=False,
            )
            session.add(camera)
            await session.flush()

            # Compute MediaMTX path manually
            mt_path = f"tenant-{tenant_id}/cam-{camera.id}"
            source_url = cam_data.get("rtsp") or ""
            ok = await mt.add_path(mt_path, source_url=source_url)
            status = "✓" if ok else "✗"
            rtsp_info = (cam_data.get("rtsp") or "N/A")[:50]
            print(f"  [{status}] {camera.name} | {cam_data['proto']} | rtsp={rtsp_info}")
            if not ok:
                print(f"      ⚠ MediaMTX path não provisionado (câmera ficará offline até o stream chegar)")
            created += 1

        print(f"\n{created} câmeras criadas com sucesso!")
        print("As câmeras RTSP_pull serão testadas pelo MediaMTX automaticamente.")
        print("As câmeras RTMP_push aguardam o stream ser enviado.")

    await close_db()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()

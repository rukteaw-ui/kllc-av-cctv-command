import aiosqlite
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from app.config import DB_PATH, CAMERA_CHANNELS

# ICT Timezone (UTC+7)
ICT = timezone(timedelta(hours=7))

def get_current_time_str() -> str:
    return datetime.now(ICT).strftime("%Y-%m-%d %H:%M:%S")

async def init_db():
    """Initialize database tables and seed default camera data."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA foreign_keys=ON;")

        # Table 1: persons
        await db.execute("""
            CREATE TABLE IF NOT EXISTS persons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                person_code TEXT UNIQUE,
                full_name TEXT NOT NULL,
                library_name TEXT,
                fdid TEXT,
                pid TEXT,
                consent_status TEXT DEFAULT 'CONSENTED',
                updated_at DATETIME
            );
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_persons_code ON persons(person_code);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_persons_lib ON persons(library_name);")

        # Table 2: access_events
        await db.execute("""
            CREATE TABLE IF NOT EXISTS access_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_time DATETIME NOT NULL,
                channel_id INTEGER NOT NULL,
                camera_name TEXT,
                match_status TEXT NOT NULL,
                person_code TEXT,
                full_name TEXT,
                library_name TEXT,
                similarity REAL DEFAULT 0.0,
                direction TEXT DEFAULT 'IN',
                snapshot_url TEXT
            );
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_time ON access_events(event_time);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_match ON access_events(match_status);")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_events_channel ON access_events(channel_id);")

        # Table 3: cameras
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cameras (
                channel_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                location_label TEXT,
                is_active BOOLEAN DEFAULT 1
            );
        """)

        # Seed cameras from config if empty
        cursor = await db.execute("SELECT COUNT(*) FROM cameras;")
        count = (await cursor.fetchone())[0]
        if count == 0:
            for ch_id, cam in CAMERA_CHANNELS.items():
                await db.execute("""
                    INSERT INTO cameras (channel_id, name, location_label, is_active)
                    VALUES (?, ?, ?, ?);
                """, (cam["channel_id"], cam["name"], cam["location_label"], 1 if cam["is_active"] else 0))

        await db.commit()

async def insert_access_event(event_data: Dict[str, Any]) -> int:
    """Insert a single face recognition access event into the database."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO access_events (
                event_time, channel_id, camera_name, match_status,
                person_code, full_name, library_name, similarity,
                direction, snapshot_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            event_data.get("event_time", get_current_time_str()),
            event_data.get("channel_id", 1),
            event_data.get("camera_name", "Unknown Camera"),
            event_data.get("match_status", "UNKNOWN"),
            event_data.get("person_code"),
            event_data.get("full_name"),
            event_data.get("library_name"),
            float(event_data.get("similarity", 0.0)),
            event_data.get("direction", "IN"),
            event_data.get("snapshot_url")
        ))
        await db.commit()
        return cursor.lastrowid

async def get_access_events(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    channel_id: Optional[int] = None,
    match_status: Optional[str] = None,
    library_name: Optional[str] = None,
    collapse_unknowns: bool = False,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """Retrieve access events with flexible filtering and collapse unknown option."""
    query = "SELECT id, event_time, channel_id, camera_name, match_status, person_code, full_name, library_name, similarity, direction, snapshot_url FROM access_events WHERE 1=1"
    params = []

    if start_date:
        query += " AND event_time >= ?"
        params.append(f"{start_date} 00:00:00")
    if end_date:
        query += " AND event_time <= ?"
        params.append(f"{end_date} 23:59:59")
    if search:
        query += " AND (person_code LIKE ? OR full_name LIKE ?)"
        term = f"%{search.strip()}%"
        params.extend([term, term])
    if channel_id:
        query += " AND channel_id = ?"
        params.append(channel_id)
    if match_status:
        query += " AND match_status = ?"
        params.append(match_status.upper())
    if library_name:
        query += " AND library_name = ?"
        params.append(library_name)

    # Order by event_time descending
    query += " ORDER BY event_time DESC, id DESC"

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

    results = []
    consecutive_unknown_count = 0
    prev_channel = None

    for row in rows:
        item = dict(row)
        if collapse_unknowns:
            if item["match_status"] == "UNKNOWN":
                if prev_channel == item["channel_id"]:
                    consecutive_unknown_count += 1
                    # Skip duplicate consecutive unknown for the same channel
                    continue
                else:
                    prev_channel = item["channel_id"]
                    consecutive_unknown_count = 1
            else:
                prev_channel = None
                consecutive_unknown_count = 0

        results.append(item)

    total_count = len(results)
    paginated_results = results[offset: offset + limit]

    return {
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "items": paginated_results
    }

async def get_daily_stats(date_str: Optional[str] = None) -> Dict[str, Any]:
    """Calculate daily summary metrics for dashboard."""
    if not date_str:
        date_str = datetime.now(ICT).strftime("%Y-%m-%d")

    async with aiosqlite.connect(DB_PATH) as db:
        # Total, Matched, Unknown
        cursor = await db.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN match_status = 'MATCHED' THEN 1 ELSE 0 END) as matched,
                SUM(CASE WHEN match_status = 'UNKNOWN' THEN 1 ELSE 0 END) as unknown,
                SUM(CASE WHEN direction = 'IN' THEN 1 ELSE 0 END) as in_count,
                SUM(CASE WHEN direction = 'OUT' THEN 1 ELSE 0 END) as out_count,
                COUNT(DISTINCT CASE WHEN match_status = 'MATCHED' THEN person_code ELSE NULL END) as unique_persons
            FROM access_events
            WHERE event_time >= ? AND event_time <= ?;
        """, (f"{date_str} 00:00:00", f"{date_str} 23:59:59"))
        row = await cursor.fetchone()

        total = row[0] or 0
        matched = row[1] or 0
        unknown = row[2] or 0
        in_count = row[3] or 0
        out_count = row[4] or 0
        unique_persons = row[5] or 0
        match_rate = round((matched / total * 100), 1) if total > 0 else 0.0

        # Channel breakdown
        cursor_ch = await db.execute("""
            SELECT channel_id, camera_name, COUNT(*) as count
            FROM access_events
            WHERE event_time >= ? AND event_time <= ?
            GROUP BY channel_id, camera_name;
        """, (f"{date_str} 00:00:00", f"{date_str} 23:59:59"))
        channels_breakdown = [
            {"channel_id": r[0], "camera_name": r[1], "count": r[2]}
            for r in await cursor_ch.fetchall()
        ]

    return {
        "date": date_str,
        "total_events": total,
        "matched_count": matched,
        "unknown_count": unknown,
        "in_count": in_count,
        "out_count": out_count,
        "unique_persons": unique_persons,
        "match_rate_percentage": match_rate,
        "channels_breakdown": channels_breakdown
    }

async def upsert_person(person: Dict[str, Any]) -> None:
    """Insert or update person record synced from NVR FDLib."""
    async with aiosqlite.connect(DB_PATH) as db:
        now = get_current_time_str()
        await db.execute("""
            INSERT INTO persons (
                person_code, full_name, library_name, fdid, pid, consent_status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(person_code) DO UPDATE SET
                full_name = excluded.full_name,
                library_name = excluded.library_name,
                fdid = excluded.fdid,
                pid = excluded.pid,
                consent_status = excluded.consent_status,
                updated_at = excluded.updated_at;
        """, (
            person.get("person_code"),
            person.get("full_name"),
            person.get("library_name", "KLLC STAFF"),
            person.get("fdid"),
            person.get("pid"),
            person.get("consent_status", "CONSENTED"),
            now
        ))
        await db.commit()

async def get_persons(
    search: Optional[str] = None,
    library_name: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """Retrieve list of synced personnel."""
    query = "SELECT id, person_code, full_name, library_name, fdid, pid, consent_status, updated_at FROM persons WHERE 1=1"
    params = []

    if search:
        query += " AND (person_code LIKE ? OR full_name LIKE ?)"
        term = f"%{search.strip()}%"
        params.extend([term, term])
    if library_name:
        query += " AND library_name = ?"
        params.append(library_name)

    query += " ORDER BY person_code ASC"

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

    total = len(rows)
    items = [dict(r) for r in rows[offset: offset + limit]]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items
    }

async def get_cameras() -> List[Dict[str, Any]]:
    """Retrieve all camera configurations."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT channel_id, name, location_label, is_active FROM cameras ORDER BY channel_id ASC;")
        return [dict(r) for r in await cursor.fetchall()]

async def update_camera_status(channel_id: int, is_active: bool) -> None:
    """Update active status of a camera channel."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE cameras SET is_active = ? WHERE channel_id = ?;", (1 if is_active else 0, channel_id))
        await db.commit()

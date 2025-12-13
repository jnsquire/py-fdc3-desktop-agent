# SQLite implementation of storage interfaces

import aiosqlite
import json
import logging
from typing import List, Optional
from .interfaces import (
    Storage,
    AppDirectoryRepository,
    LaunchConfigRepository,
    OriginRepository,
    AppMetadata,
    LaunchConfig,
)

logger = logging.getLogger(__name__)


class SqliteAppDirectoryRepository(AppDirectoryRepository):
    """SQLite implementation of app directory repository"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get_app_metadata(self, app_id: str) -> Optional[AppMetadata]:
        """Get app metadata by app_id"""
        async with self.db.execute(
            "SELECT name, version, description, icons, intents FROM apps WHERE app_id = ?",
            (app_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                name, version, description, icons_json, intents_json = row
                icons = json.loads(icons_json) if icons_json else []
                intents = json.loads(intents_json) if intents_json else []
                return AppMetadata(app_id, name, version, description, icons, intents)
        return None

    async def list_apps(self) -> List[AppMetadata]:
        """List all apps in directory"""
        apps = []
        async with self.db.execute(
            "SELECT app_id, name, version, description, icons, intents FROM apps"
        ) as cursor:
            async for row in cursor:
                app_id, name, version, description, icons_json, intents_json = row
                icons = json.loads(icons_json) if icons_json else []
                intents = json.loads(intents_json) if intents_json else []
                apps.append(
                    AppMetadata(app_id, name, version, description, icons, intents)
                )
        return apps

    async def add_app(self, metadata: AppMetadata) -> None:
        """Add or update app in directory"""
        icons_json = json.dumps(metadata.icons)
        intents_json = json.dumps(metadata.intents)
        await self.db.execute(
            """
            INSERT OR REPLACE INTO apps (app_id, name, version, description, icons, intents)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                metadata.app_id,
                metadata.name,
                metadata.version,
                metadata.description,
                icons_json,
                intents_json,
            ),
        )
        await self.db.commit()

    async def remove_app(self, app_id: str) -> None:
        """Remove app from directory"""
        await self.db.execute("DELETE FROM apps WHERE app_id = ?", (app_id,))
        await self.db.commit()


class SqliteLaunchConfigRepository(LaunchConfigRepository):
    """SQLite implementation of launch config repository"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get_launch_config(self, app_id: str) -> Optional[LaunchConfig]:
        """Get launch config for app"""
        async with self.db.execute(
            "SELECT command, args, env, cwd, timeout FROM launch_configs WHERE app_id = ?",
            (app_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                command, args_json, env_json, cwd, timeout = row
                args = json.loads(args_json) if args_json else []
                env = json.loads(env_json) if env_json else {}
                return LaunchConfig(app_id, command, args, env, cwd, timeout)
        return None

    async def set_launch_config(self, config: LaunchConfig) -> None:
        """Set launch config for app"""
        args_json = json.dumps(config.args)
        env_json = json.dumps(config.env)
        await self.db.execute(
            """
            INSERT OR REPLACE INTO launch_configs (app_id, command, args, env, cwd, timeout)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                config.app_id,
                config.command,
                args_json,
                env_json,
                config.cwd,
                config.timeout,
            ),
        )
        await self.db.commit()

    async def remove_launch_config(self, app_id: str) -> None:
        """Remove launch config for app"""
        await self.db.execute("DELETE FROM launch_configs WHERE app_id = ?", (app_id,))
        await self.db.commit()

    async def list_launch_configs(self) -> List[LaunchConfig]:
        """List all launch configs"""
        async with self.db.execute(
            "SELECT app_id, command, args, env, cwd, timeout FROM launch_configs"
        ) as cursor:
            rows = await cursor.fetchall()
            configs = []
            for row in rows:
                app_id, command, args_json, env_json, cwd, timeout = row
                args = json.loads(args_json) if args_json else []
                env = json.loads(env_json) if env_json else {}
                configs.append(LaunchConfig(app_id, command, args, env, cwd, timeout))
            return configs


class SqliteOriginRepository(OriginRepository):
    """SQLite implementation of origin repository"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get_allowed_origins(self, app_id: str) -> List[str]:
        """Get allowed origins for app"""
        async with self.db.execute(
            "SELECT origins FROM origins WHERE app_id = ?", (app_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                (origins_json,) = row
                return json.loads(origins_json) if origins_json else []
        return []

    async def set_allowed_origins(self, app_id: str, origins: List[str]) -> None:
        """Set allowed origins for app"""
        origins_json = json.dumps(origins)
        await self.db.execute(
            """
            INSERT OR REPLACE INTO origins (app_id, origins)
            VALUES (?, ?)
            """,
            (app_id, origins_json),
        )
        await self.db.commit()


class SqliteStorage(Storage):
    """SQLite implementation of storage interface"""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
        self._apps_repo: Optional[SqliteAppDirectoryRepository] = None
        self._launch_repo: Optional[SqliteLaunchConfigRepository] = None
        self._origins_repo: Optional[SqliteOriginRepository] = None

    @property
    def apps(self) -> AppDirectoryRepository:
        """App directory repository"""
        if self._apps_repo is None:
            raise RuntimeError("Storage not initialized")
        return self._apps_repo

    @property
    def launch_configs(self) -> LaunchConfigRepository:
        """Launch config repository"""
        if self._launch_repo is None:
            raise RuntimeError("Storage not initialized")
        return self._launch_repo

    @property
    def origins(self) -> OriginRepository:
        """Origin repository"""
        if self._origins_repo is None:
            raise RuntimeError("Storage not initialized")
        return self._origins_repo

    async def initialize(self) -> None:
        """Initialize storage (create tables, etc.)"""
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row

        # Create tables
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS apps (
                app_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version TEXT,
                description TEXT,
                icons TEXT,  -- JSON array
                intents TEXT  -- JSON array
            );

            CREATE TABLE IF NOT EXISTS launch_configs (
                app_id TEXT PRIMARY KEY,
                command TEXT NOT NULL,
                args TEXT,  -- JSON array
                env TEXT,  -- JSON object
                cwd TEXT,
                timeout INTEGER DEFAULT 30
            );

            CREATE TABLE IF NOT EXISTS origins (
                app_id TEXT PRIMARY KEY,
                origins TEXT  -- JSON array
            );
        """
        )

        # Create repositories
        self._apps_repo = SqliteAppDirectoryRepository(self._db)
        self._launch_repo = SqliteLaunchConfigRepository(self._db)
        self._origins_repo = SqliteOriginRepository(self._db)

        logger.info(f"SQLite storage initialized at {self.db_path}")

    async def close(self) -> None:
        """Close storage connections"""
        if self._db:
            await self._db.close()
            self._db = None
            logger.info("SQLite storage closed")

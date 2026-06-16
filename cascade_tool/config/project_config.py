import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime


class ProjectConfig:
    """项目配置管理 - 按项目保存常用检查配置"""

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            self.base_dir = Path.home() / ".cascade_tool"
        self.projects_dir = self.base_dir / "projects"
        self._ensure_dirs()

    def _ensure_dirs(self):
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)

    def list_projects(self) -> List[Dict[str, Any]]:
        """列出所有项目"""
        projects = []
        if not self.projects_dir.exists():
            return projects
        for proj_dir in self.projects_dir.iterdir():
            if proj_dir.is_dir():
                config_file = proj_dir / "config.json"
                if config_file.exists():
                    try:
                        with open(config_file, "r", encoding="utf-8") as f:
                            cfg = json.load(f)
                        projects.append({
                            "name": proj_dir.name,
                            "description": cfg.get("description", ""),
                            "created_at": cfg.get("created_at", ""),
                            "updated_at": cfg.get("updated_at", "")
                        })
                    except Exception:
                        projects.append({
                            "name": proj_dir.name,
                            "description": "(配置文件损坏)",
                            "created_at": "",
                            "updated_at": ""
                        })
        return projects

    def project_exists(self, project_name: str) -> bool:
        """检查项目是否存在"""
        return (self.projects_dir / project_name).exists()

    def create_project(self, project_name: str, description: str = "") -> Dict[str, Any]:
        """创建新项目"""
        proj_dir = self.projects_dir / project_name
        if proj_dir.exists():
            raise ValueError(f"项目 '{project_name}' 已存在")

        proj_dir.mkdir(parents=True)
        now = datetime.now().isoformat()
        config = {
            "name": project_name,
            "description": description,
            "created_at": now,
            "updated_at": now,
            "check_config": {
                "timeout": 5,
                "retry_count": 2,
                "check_channels": True,
                "check_devices": True,
                "check_platforms": True
            },
            "platforms": [],
            "devices": [],
            "channels": []
        }
        self._save_config(project_name, config)
        return config

    def get_project_dir(self, project_name: str) -> Path:
        """获取项目目录"""
        return self.projects_dir / project_name

    def get_config(self, project_name: str) -> Dict[str, Any]:
        """获取项目配置"""
        config_file = self.projects_dir / project_name / "config.json"
        if not config_file.exists():
            raise ValueError(f"项目 '{project_name}' 不存在")
        with open(config_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def update_config(self, project_name: str, config: Dict[str, Any]):
        """更新项目配置"""
        config["updated_at"] = datetime.now().isoformat()
        self._save_config(project_name, config)

    def _save_config(self, project_name: str, config: Dict[str, Any]):
        config_file = self.projects_dir / project_name / "config.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def delete_project(self, project_name: str):
        """删除项目"""
        import shutil
        proj_dir = self.projects_dir / project_name
        if not proj_dir.exists():
            raise ValueError(f"项目 '{project_name}' 不存在")
        shutil.rmtree(proj_dir)

    def save_data_file(self, project_name: str, filename: str, data: Any, fmt: str = "json"):
        """保存数据文件到项目目录"""
        proj_dir = self.get_project_dir(project_name)
        proj_dir.mkdir(parents=True, exist_ok=True)
        file_path = proj_dir / filename

        if fmt == "json":
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        elif fmt == "txt":
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(str(data))
        else:
            raise ValueError(f"不支持的格式: {fmt}")

    def load_data_file(self, project_name: str, filename: str, fmt: str = "json") -> Any:
        """加载项目数据文件"""
        file_path = self.projects_dir / project_name / filename
        if not file_path.exists():
            return None
        if fmt == "json":
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        elif fmt == "txt":
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        else:
            raise ValueError(f"不支持的格式: {fmt}")

"""Plugin loader and manager."""
import importlib
import sys
from pathlib import Path
from typing import Dict, List, Optional
import config
from plugin_base import DataSourcePlugin


class PluginLoader:
    """Loads and manages data source plugins."""
    
    def __init__(self):
        self.plugins: Dict[str, DataSourcePlugin] = {}
        self._load_plugins()
    
    def _load_plugins(self):
        """Load all plugins from the plugins directory."""
        plugins_dir = config.PLUGINS_DIR
        
        for plugin_dir in plugins_dir.iterdir():
            if not plugin_dir.is_dir():
                continue
            
            plugin_name = plugin_dir.name
            plugin_file = plugin_dir / "plugin.py"
            
            if not plugin_file.exists():
                continue
            
            try:
                # Load plugin module
                spec = importlib.util.spec_from_file_location(
                    f"plugins.{plugin_name}.plugin",
                    plugin_file
                )
                module = importlib.util.module_from_spec(spec)
                sys.modules[f"plugins.{plugin_name}.plugin"] = module
                spec.loader.exec_module(module)
                
                # Find plugin class (should be named Plugin)
                if hasattr(module, 'Plugin'):
                    plugin_class = module.Plugin
                    # Always instantiate plugins (enabled state is now in database, not config.json)
                    try:
                        plugin_instance = plugin_class()
                        self.plugins[plugin_name] = plugin_instance
                        print(f"Loaded plugin: {plugin_name}")
                    except Exception as instance_error:
                        print(f"Error instantiating plugin {plugin_name}: {instance_error}")
                else:
                    print(f"Plugin {plugin_name} does not have a Plugin class")
            except Exception as e:
                print(f"Error loading plugin {plugin_name}: {e}")
    
    def get_plugin(self, plugin_name: str) -> Optional[DataSourcePlugin]:
        """Get a plugin by name."""
        return self.plugins.get(plugin_name)
    
    def get_all_plugins(self) -> Dict[str, DataSourcePlugin]:
        """Get all loaded plugins."""
        return self.plugins
    
    def list_plugins(self) -> List[str]:
        """List all available plugin names."""
        return list(self.plugins.keys())


# Import importlib.util for dynamic loading
import importlib.util


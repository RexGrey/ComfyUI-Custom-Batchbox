from .nodes import NanoBananaPro, create_dynamic_node
from .config_manager import config_manager

# 1. Base Mappings (Universal Node)
NODE_CLASS_MAPPINGS = {
    "NanoBananaPro": NanoBananaPro
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NanoBananaPro": "Nano Banana Pro (Universal)"
}

# 2. Dynamic Registration
# Scan config for "dynamic_node" definitions
try:
    # Reload config to be sure
    config_manager.load_config()
    presets = config_manager.get_presets()
    
    for p_name in presets:
        p_cfg = config_manager.get_preset_config(p_name)
        if p_cfg and "dynamic_node" in p_cfg:
            # Create the class dynamically
            cls_name, disp_name, cls_obj = create_dynamic_node(p_name, p_cfg["dynamic_node"])
            
            # Register
            NODE_CLASS_MAPPINGS[cls_name] = cls_obj
            NODE_DISPLAY_NAME_MAPPINGS[cls_name] = disp_name
            print(f"[ComfyUI-Custom-Batchbox] Registered dynamic node: {disp_name} ({cls_name})")

except Exception as e:
    print(f"[ComfyUI-Custom-Batchbox] Error loading dynamic nodes: {e}")

WEB_DIRECTORY = "./web"
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

# ==========================================
# 3. API Management Endpoints
# ==========================================
import server
from aiohttp import web

@server.PromptServer.instance.routes.get("/api/batchbox/config")
async def get_config(request):
    try:
        data = config_manager.get_raw_config()
        return web.json_response(data)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/batchbox/config")
async def save_config(request):
    try:
        data = await request.json()
        config_manager.save_config_data(data)
        return web.json_response({"status": "success"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

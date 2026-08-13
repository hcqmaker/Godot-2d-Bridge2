bl_info = {
    "name": "Godot 2d Bridge",
    "author": "TorKai",
    "version": (1, 0),
    "blender": (2, 80, 0),
    "location": "View3D > Sidebar > Godot 2d Bridge",
    "description": "Used to bridge Blender and Godot's 2d mesh, bone, and skinning functionality",
    "warning": "",
    "doc_url": "",
    "category": "Godot",
}

import bpy

from bpy.props import PointerProperty

from bpy.app.handlers import (
    depsgraph_update_post,
    undo_post,
    redo_post
)

from .gd2db_operators_and_properties import (
    GODOT_2D_BRIDGE_OT_scene_selection,
    GODOT_2D_BRIDGE_OT_export,
    GODOT_2D_BRIDGE_OT_2d_view,

    GODOT_2D_BRIDGE_OT_import_sprites,
    GODOT_2D_BRIDGE_OT_add_plane,
    GODOT_2D_BRIDGE_OT_add_armature,
    GODOT_2D_BRIDGE_OT_add_bone,
    GODOT_2D_BRIDGE_OT_lock_pose_bones,

    GODOT_2D_BRIDGE_OT_export_root,
    GODOT_2D_BRIDGE_OT_export_47,
    GODOT_2D_BRIDGE_OT_clear,
    GODOT_2D_BRIDGE_OT_2d_object_toggle,
    GODOT_2D_BRIDGE_OT_apply_material,
    Godot2dBridgeProperties
)

from .gd2db_ui import (
    GODOT_2D_BRIDGE_PT_export_panel,
    GODOT_2D_BRIDGE_PT_setup_panel,
    GODOT_2D_BRIDGE_PT_export_panel_47
)

from .gd2db_2d_constraints import (
    gd2db_constraint_changer,
    remove_all_constraints,
    gd2db_undo_redo_activator
)

from bpy.utils import (
    register_class,
    unregister_class
)


# =========================================================================
# Property Functions:
# =========================================================================


# used to make gd2db_object_2d readonly
def get_object_2d(self):
    setter = False
    if self.get("gd2db_object_2d"):
        setter = self["gd2db_object_2d"]
    return setter


# returns a list of enumerator property items containing the names of available images within the blender file
def gd2db_texture_items(_self, _context):
    item_list = [("None", "None", "")]
    for img in bpy.data.images:
        item_list.append((img.name, img.name, ""))
    return item_list


# =========================================================================
# Registration:
# =========================================================================


classes = (
    GODOT_2D_BRIDGE_OT_apply_material,
    GODOT_2D_BRIDGE_OT_scene_selection,
    GODOT_2D_BRIDGE_OT_export,
    GODOT_2D_BRIDGE_OT_2d_view,

    GODOT_2D_BRIDGE_OT_import_sprites,
    GODOT_2D_BRIDGE_OT_add_plane,
    GODOT_2D_BRIDGE_OT_add_armature,
    GODOT_2D_BRIDGE_OT_add_bone,
    GODOT_2D_BRIDGE_OT_lock_pose_bones,

    GODOT_2D_BRIDGE_OT_export_root,
    GODOT_2D_BRIDGE_OT_export_47,
    GODOT_2D_BRIDGE_OT_clear,
    GODOT_2D_BRIDGE_OT_2d_object_toggle,
    GODOT_2D_BRIDGE_PT_setup_panel,
    GODOT_2D_BRIDGE_PT_export_panel_47,
    GODOT_2D_BRIDGE_PT_export_panel,
    Godot2dBridgeProperties
)

addon_keymaps = []
def register_keymaps():

    # km = wm.keyconfigs.addon.keymaps.new(name=idname, space_type=space_type)
    # kmi = km.keymap_items.new(idname, type, value, ctrl=true)
    # properties = kmi.get("properties")
    # for name, value in properties:
    #   setattr(kmi.properties, name, value)
    # keymaps = keymaps.append((km,kmi))

    # blender_python_reference_5_2/bpy.types.KeyMaps.html#bpy.types.KeyMaps
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
        kmi = km.keymap_items.new("view3d.move", "MIDDLEMOUSE", "PRESS")
        kmi.active = False

    addon = bpy.context.window_manager.keyconfigs.addon
    if addon is None:
        return 
    # km = addon.keymaps.new(name="Bone Editor", space_type="NODE_EDITOR")
    km = addon.keymaps.new(name="3D View", space_type="VIEW_3D")
    # km = addon.keymaps.new(name="3D View", space_type="NODE_EDITOR") #
    kmi = km.keymap_items.new("gd2db.edit_add_bone", type="A", shift=True, value="PRESS")
    kmi.properties.bone_name = "Bone"


    wm = bpy.context.window_manager    # get window manager
    kc = wm.keyconfigs.default.keymaps    # get default keymap
    tmp_add_bone = kc['Armature'].keymap_items.get('armature.bone_primitive_add')
    tmp_add_bone.active = False    # disable that item

    addon_keymaps.append(km)
    pass

def unregister_keymaps():
    wm = bpy.context.window_manager
    for km in addon_keymaps:
        for kmi in km.keymap_items:
            km.keymap_items.remove(kmi)
        wm.keyconfigs.addon.keymaps.remove(km)
    addon_keymaps.clear()

    kc = wm.keyconfigs.default.keymaps    # get default keymap
    tmp_add_bone = kc['Armature'].keymap_items.get('armature.bone_primitive_add')
    tmp_add_bone.active = True    # disable that item
    pass


def register():

    bpy.types.Object.gd2db_object_2d = bpy.props.BoolProperty(
        name="",
        get=get_object_2d,
        options={'HIDDEN'}
    )

    # noinspection PyTypeChecker
    bpy.types.Object.gd2db_texture_image = bpy.props.EnumProperty(
        name="gd2db_texture_image",
        items=gd2db_texture_items,
        options={'HIDDEN'}
    )

    bpy.types.Object.gd2db_image_width = bpy.props.IntProperty(
        name="gd2db_image_width",
        subtype="PIXEL",
        min=1,
        default=500,
        options={'HIDDEN'}
    )

    bpy.types.Object.gd2db_image_height = bpy.props.IntProperty(
        name="gd2db_image_height",
        subtype="PIXEL",
        min=1,
        default=500,
        options={'HIDDEN'}
    )

    depsgraph_update_post.append(gd2db_constraint_changer)
    redo_post.append(gd2db_undo_redo_activator)
    undo_post.append(gd2db_undo_redo_activator)

    for cls in classes:
        register_class(cls)
    bpy.types.Scene.godot_2d_bridge_tools = PointerProperty(type=Godot2dBridgeProperties)

    register_keymaps()


def unregister():

    unregister_keymaps()

    del bpy.types.Object.gd2db_object_2d
    del bpy.types.Object.gd2db_texture_image
    del bpy.types.Object.gd2db_image_width
    del bpy.types.Object.gd2db_image_height

    remove_all_constraints()
    depsgraph_update_post.remove(gd2db_constraint_changer)
    redo_post.remove(gd2db_undo_redo_activator)
    undo_post.remove(gd2db_undo_redo_activator)

    for cls in classes:
        unregister_class(cls)
    del bpy.types.Scene.godot_2d_bridge_tools


if __name__ == "__main__":
    register()

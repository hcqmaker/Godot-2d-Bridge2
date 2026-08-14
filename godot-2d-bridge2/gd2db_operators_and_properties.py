from typing import Literal

import bpy
import json,os,math
from mathutils import Vector, Matrix, Quaternion
from time import perf_counter

from bpy.types import (
    Context,
    Event,
    Operator,
    PropertyGroup
)

from bpy.props import (
    IntProperty,
    StringProperty,
    BoolProperty,
    EnumProperty,
    CollectionProperty,
)

from bpy_extras.io_utils import (
    ImportHelper,
    ExportHelper
)

from math import (
    prod,
    radians
)

from .gd2db_utilities import (
    rotate_around_point,
    ProgressReporter
)

from .gd2db_2d_constraints import remove_all_constraints
from .gd2db_scene_parsing import write_godot_scene,write_godot_scene_47
from .gd2db_utilities import export_objects, custom_message_box, list_export_objects


# returns list of enumerator property items containing the name of empties within the scene that display images and
# return true for the gd2db_object_2d object property.
def available_references(_self, context):
    reference_object_list = [
        x for x in context.scene.objects
        if x.empty_display_type == 'IMAGE'
        and x.gd2db_object_2d
        and x.data is not None
        and any(x.data.size)
    ]
    if not reference_object_list:
        return [("None", "Add Reference Image", "")]
    else:
        reference_property_list = []
        for ref in reference_object_list:
            reference_property_list.append((ref.name, ref.name, f"{ref}"))
        return reference_property_list


### Custom template_list look
class GODOT_2D_BRIDGE_UL_ObjCollections(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        col = layout.row(align=True)
        col.label(text=item.name)

class Godot2dBridgeItemString(PropertyGroup):
    name: StringProperty(default='')

class Godot2dBridgeProperties(PropertyGroup):

    pixels_per_unit: IntProperty(
        name="BU =",
        subtype='PIXEL',
        min=1,
        default=100,
        description="Pixels per Blender unit. Used to determine scale within a 2d space"
    )

    godot_scene: StringProperty(
        name="",
        description="Exported objects will be added to this scene"
    )

    use_collection: BoolProperty(
        name="Collections",
        description="Export collections as 2dNodes"
    )

    selected: BoolProperty(
        name="Selected",
        description="Export selected objects only"
    )

    # noinspection PyTypeChecker
    reference_empty: EnumProperty(
        items=available_references,
        name="",
        description="Chose an image empty to apply"
    )

    mode_updater: StringProperty(
        name="",
        default="init",
        description="Used to run handler only if mode is changed"
    )

    godot_version: EnumProperty(
        items=[
            ("1", "2.1", "Does not support \"Skeleton2D\" nodes or internal vertices"),
            ("2", "3.0", "Does not support \"Skeleton2D\" nodes or internal vertices"),
            ("3", "3.1", ""),
            ("4", "3.2", ""),
            ("5", "3.3", ""),
            ("6", "3.4", ""),
            ("7", "3.5", ""),
            ("8", "3.6", ""),
            ("9", "4.0+", "Versions beyond 4.0 may be unsupported"),
        ],
        name="",
        description="Chose the version of Godot to export the scene for",
        default="7"
    )

    export_objs: CollectionProperty(type=Godot2dBridgeItemString)
    export_idx: IntProperty(default=-1)

    export_root: StringProperty(
        name="",
        default="",
        description="export godot scene root use for operator path for texture"
    )
    all_in_one:BoolProperty(
        name="all animation in one",
        description="Export animation all in in one"
    )

# returns a "2d" coordinate constrained to the min and max coordinates
def normalize_2d_coordinates(co, min_co, max_co):
    return (co[0] - min_co[0]) / (max_co[0] - min_co[0]), (co[1] - min_co[1]) / (max_co[1] - min_co[1])


# allows the user to select a godot scene that new objects will be imported into
# noinspection PyPep8Naming
class GODOT_2D_BRIDGE_OT_scene_selection(Operator, ImportHelper):
    bl_label = "Godot Scene"
    bl_idname = "gd2db.scene"
    bl_options = {'REGISTER', "UNDO"}
    bl_description = "Chose *.tscn file to export too"

    filter_glob: StringProperty(default="*.tscn", options={'HIDDEN'})

    def execute(self, context):
        # noinspection PyUnresolvedReferences
        context.scene.godot_2d_bridge_tools.godot_scene = self.filepath
        return {'FINISHED'}


# clear operator for the godot_scene property
# noinspection PyPep8Naming
class GODOT_2D_BRIDGE_OT_clear(Operator):
    bl_label = ""
    bl_idname = "gd2db.clear"
    bl_options = {'REGISTER', "UNDO"}
    bl_description = "Clear scene property"

    # noinspection PyMethodMayBeStatic
    def execute(self, context):
        context.scene.godot_2d_bridge_tools.godot_scene = ""
        return {'FINISHED'}


# builds a material from the user selected image empty and applies it to selected mesh objects
# noinspection PyPep8Naming
class GODOT_2D_BRIDGE_OT_apply_material(Operator):
    bl_label = "Apply Image"
    bl_idname = "gd2db.material"
    bl_options = {'REGISTER', "UNDO"}
    bl_description = "Apply the image displayed in the chosen empty to selected 2d meshes as a texture material"

    # noinspection PyMethodMayBeStatic
    def execute(self, context):

        # filter "2d" mesh objects for the selected objects list
        objects_to_apply = [
            x for x in context.selected_objects
            if x.type == 'MESH'
            and x.gd2db_object_2d
        ]

        # get the image empty chosen by the user
        empty = bpy.data.objects[context.scene.godot_2d_bridge_tools.reference_empty]

        # used to align the active uv of a mesh object to the relative position of the image empty
        def align_uv(object_to_align):
            # calculate the ratio of the image resolutions to the highest resolution axis
            image_ratios = tuple(x / max(empty.data.size) for x in empty.data.size)

            # calculate the min and max positions of uv points within the uv space
            min_position = (x * empty.empty_display_size for x in empty.empty_image_offset)
            min_position = (prod(x) for x in zip(min_position, empty.scale, image_ratios))
            min_position = tuple(sum(x) for x in zip(min_position, empty.location))
            max_position = (x * empty.empty_display_size + empty.empty_display_size for x in empty.empty_image_offset)
            max_position = (prod(x) for x in zip(max_position, empty.scale, image_ratios))
            max_position = tuple(sum(x) for x in zip(max_position, empty.location))

            # check if the mesh object has an uv layer and find the active uv, otherwise create a new uv layer
            if object_to_align.data.uv_layers:
                active_uv = [x for x in object_to_align.data.uv_layers if x.active_render][0]
            else:
                active_uv = object_to_align.data.uv_layers.new(name="UVMap")

            # iterate through object loops to get the vertex index for the associated uv point
            reporting_instance.start_sub_job()
            for loop in object_to_align.data.loops:
                reporting_instance.update()
                reporting_instance.adjust_update_rate()

                # get the x/y coordinate of the vertex relative to the rotation of the empty
                vertex_co = (object_to_align.matrix_world @ object_to_align.data.vertices[loop.vertex_index].co)[0:2]
                vertex_co = rotate_around_point(vertex_co, -empty.rotation_euler.z, point=(empty.location[0:2]))

                # normalize the vertex coordinate to the min and max positions of the uv and assign them to the uv
                uv_point = active_uv.data[loop.index].uv
                uv_point.x, uv_point.y = normalize_2d_coordinates(vertex_co, min_position, max_position)
            reporting_instance.end_sub_job()
            return

        # builds the material, based on the chosen image empty, to assign to the mesh object
        def create_material():
            # create a name unique to this plugin to prevent the operator from accidentally overwriting user created
            # materials or materials created by other plugins or scripts
            name = f"GD2DB: Material \"{empty.data.name}\""

            # used to check if the material exists
            def material_exists():
                exists = False
                for mat in bpy.data.materials:
                    if mat.name == name:
                        exists = True
                        break
                return exists

            # if the material exists perform the operation on that material, otherwise, create a new material
            if material_exists():
                material = bpy.data.materials[name]
            else:
                material = bpy.data.materials.new(name=name)

            # ensure use_nodes is set to true, change the blend_to alpha clip, set the threshold to 0.5, and get the
            # nodes and links for the node tree
            material.use_nodes = True
            material.blend_method = 'CLIP'
            material.alpha_threshold = 0.5
            nodes = material.node_tree.nodes
            links = material.node_tree.links

            # clear all existing nodes
            nodes.clear()

            # create and position the material nodes
            material_output = nodes.new("ShaderNodeOutputMaterial")
            material_output.location = (1200, 0)
            mix_shader = nodes.new('ShaderNodeMixShader')
            mix_shader.location = (900, 0)
            transparent_bsdf = nodes.new('ShaderNodeBsdfTransparent')
            transparent_bsdf.location = (600, 0)
            invert = nodes.new('ShaderNodeInvert')
            invert.location = (300, 0)
            texture = nodes.new('ShaderNodeTexImage')
            texture.location = (0, 0)

            # connect the nodes with links
            links.new(texture.outputs[0], mix_shader.inputs[2])
            links.new(texture.outputs[1], mix_shader.inputs[0])
            links.new(texture.outputs[1], invert.inputs[1])
            links.new(invert.outputs[0], transparent_bsdf.inputs[0])
            links.new(transparent_bsdf.outputs[0], mix_shader.inputs[1])
            links.new(mix_shader.outputs[0], material_output.inputs[0])

            # change the extension mode of the texture node to clip and assign the image in the empty to the image
            # property of the node
            texture.extension = 'CLIP'
            texture.image = empty.data
            return material

        if objects_to_apply:
            # create the material and get the image
            new_material = create_material()
            image = empty.data

            reporting_instance = ProgressReporter(
                "UV UPDATING", [x.name for x in objects_to_apply], [len(x.data.loops) for x in objects_to_apply]
            )

            # iterate through objects_to_apply, apply the new_material to active_material for each object,
            # and set the object properties based on the image
            for obj in objects_to_apply:
                obj.active_material = new_material
                obj.gd2db_texture_image = image.name
                obj.gd2db_image_width = image.size[0]
                obj.gd2db_image_height = image.size[1]
                align_uv(obj)
        return {'FINISHED'}


# toggles the gd2db_object_2d property and constrains the "2d" objects to the x/y plane using handlers
# noinspection PyPep8Naming
class GODOT_2D_BRIDGE_OT_2d_object_toggle(Operator):
    bl_label = "2d/3d Object"
    bl_idname = "gd2db.convert"
    bl_options = {'REGISTER', "UNDO"}
    bl_description = "Toggle the selected objects' status as 2d object"

    # noinspection PyMethodMayBeStatic
    def execute(self, context):
        # filter mesh, armature, and image empty object types from the selected objects list
        objects_to_apply = (
            x for x in context.selected_objects
            if x.type == 'MESH'
            or x.type == 'ARMATURE'
            or x.empty_display_type == 'IMAGE'
        )

        # operator needs to change the active object to change the position of edit bones, so the currently active
        # object is saved to a variable for reapplication at the end of the operator
        active_object = context.view_layer.objects.active

        # iterate through objects_to_apply and check the gd2db_object_2d property to determine which actions to take
        for obj in objects_to_apply:
            if not obj.gd2db_object_2d:

                # apply rotation, Blender won't apply transforms to empties displaying images with multiple users,
                # so the image is removed from the empty and reapplied to get around this
                if obj.type == 'EMPTY':
                    current_image = obj.data
                    obj.data = None
                    bpy.ops.object.transform_apply(location=False, scale=False, properties=False)
                    obj.data = current_image
                else:
                    bpy.ops.object.transform_apply(location=False, scale=False, properties=False)

                # set the gd2db_object_2d property to true to indicate to the rest of the addon this object is a "2d"
                # object, set the rotation mode to xyz euler, 0 the z location, and set the z scale to 1
                obj['gd2db_object_2d'] = True
                obj.rotation_mode = 'XYZ'
                # obj.location.z = 0
                obj.scale.z = 1

                # lock the x and y rotation, and the z location and scale properties of the object
                obj.lock_rotation[0] = True
                obj.lock_rotation[1] = True
                obj.lock_scale[2] = True
                obj.lock_location[2] = True

                # check if the object is a mesh or an armature, if it's a mesh then create texture image properties, and
                # 0 the z coordinates of vertices
                if obj.type == 'MESH':
                    obj.gd2db_texture_image = "None"
                    obj.gd2db_image_width = 500
                    obj.gd2db_image_height = 500
                    for vert in obj.data.vertices:
                        vert.co.z = 0

                # if the object is an armature then iterate through its pose and edit bones and set there position and
                # rotation to the x/y plane
                elif obj.type == 'ARMATURE':
                    for bone in obj.pose.bones:
                        # change the pose bone's rotation mode to xyz euler, 0 the bones z location and x/y rotation,
                        # and set the z scale to 1
                        bone.rotation_mode = 'XYZ'
                        bone.location.z = 0
                        bone.rotation_euler.x = 0
                        bone.rotation_euler.y = 0
                        bone.scale.z = 1

                        # lock the x and y rotation, and the z location and scale properties of the pose bone
                        bone.lock_location[2] = True
                        bone.lock_scale[2] = True
                        bone.lock_rotation[0] = True
                        bone.lock_rotation[1] = True

                    # change the active object to the armature and put it in edit mode
                    context.view_layer.objects.active = obj
                    bpy.ops.object.mode_set(mode='EDIT')

                    edit_bones = obj.data.edit_bones
                    for bone in edit_bones:

                        # get the x/y coordinates of the head and tail of the edit bone and check if they're the same
                        # if they are the bone is rotated 90 degrees to prevent removing the bone when the z coordinates
                        # are zeroed
                        bone_head_x_y = bone.head.x, bone.head.y
                        bone_tail_x_y = bone.tail.x, bone.tail.y
                        if bone_head_x_y == bone_tail_x_y:
                            bone_point = bone.head.x, bone.head.z
                            new_tail_x_z = rotate_around_point((bone.tail.x, bone.tail.z), radians(90), bone_point)
                            bone.tail.x, bone.tail.z = new_tail_x_z

                        # 0 the head, tail, and roll
                        bone.head.z = 0
                        bone.tail.z = 0
                        bone.roll = 0

                    # reset the mode to object mode
                    bpy.ops.object.mode_set(mode='OBJECT')
            else:
                # remove the plugin related properties, the plugin will no longer recognize this object as a "2d" object
                # and all locked properties can now be changed by the user
                del obj["gd2db_object_2d"]
                if obj.type == 'MESH':
                    if (hasattr(obj, "gd2db_texture_image")):
                        del obj["gd2db_texture_image"]
                        del obj["gd2db_image_width"]
                        del obj["gd2db_image_height"]

        # reset the active object and remove all constraint handlers and timers
        context.view_layer.objects.active = active_object
        if not any((x.gd2db_object_2d for x in bpy.data.objects)):
            remove_all_constraints()

        list_export_objects()

        return {'FINISHED'}

# update export list
class GODOT_2D_BRIDGE_OT_list_export_objects(Operator):
    bl_label = "Export Objects List"
    bl_idname = "gd2db.list_export_objects"
    bl_options = {'REGISTER', }
    bl_description = "list all export objects"

    def execute(self, context):
        list_export_objects()
        return {'FINISHED'}

# exports objects and collections based on user defined parameters
# noinspection PyPep8Naming
class GODOT_2D_BRIDGE_OT_export(Operator, ExportHelper):
    bl_label = "Export"
    bl_idname = "gd2db.export"
    bl_description = "Export objects to a *.tscn file"

    # set the filename extension and filter for ExportHelper
    filename_ext = ".tscn"
    filter_glob: StringProperty(default="*.tscn", options={'HIDDEN'})

    def execute(self, _context):
        # get the start time of the export process
        export_start_time = perf_counter()

        # use the gd2db_scene_parsing module to write a new *.tscn file
        # noinspection PyUnresolvedReferences
        export_success = write_godot_scene(self.filepath)

        if export_success:
            # parse the list of exported objects
            exported_list = [f"\"{x.name}\"" for x in export_objects()]
            if len(exported_list) > 2:
                exported_list = ", ".join(exported_list[0:-1]), exported_list[-1]
                exported_list = f"{exported_list[0]}, and {exported_list[1]}"
            elif len(exported_list) > 1:
                exported_list = f"{exported_list[0]} and {exported_list[1]}"
            else:
                exported_list = exported_list[0]

            # generate a successful export popup indicating the objects exported and the elapsed time for export process
            custom_message_box(
                message=f"{exported_list} successfully exported in {perf_counter() - export_start_time:05.2f}s.",
                title="Success!",
                icon='INFO'
            )
        return {'FINISHED'}


def _inline_set_view(mode):
    # print("model:", mode)
    if mode == "2D":
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type == "VIEW_3D":
                    active_space_data = area.spaces[0]
                    if active_space_data != None:
                        if hasattr(active_space_data, "region_3d"):
                            bpy.ops.view3d.view_axis(
                                type="TOP",
                                align_active=False,
                                relative=False,
                            )

    elif mode == "3D":
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type == "VIEW_3D":
                    active_space_data = area.spaces[0]
                    if active_space_data != None:
                        if hasattr(active_space_data, "region_3d"):
                            region_3d = active_space_data.region_3d
                            region_3d.view_perspective = "PERSP"


def _inline_set_middle_mouse_move(enable):
    km = bpy.context.window_manager.keyconfigs.addon.keymaps["3D View"]
    if ('view3d.move' in km.keymap_items):
        km.keymap_items["view3d.move"].active = enable


class GODOT_2D_BRIDGE_OT_2d_view(Operator):
    bl_label = "2D/3D View"
    bl_idname = "gd2db.set_2d_view"
    bl_options = {'REGISTER'}
    bl_description = "set 2d/3d veiw"

    view2d:BoolProperty(name="2D/3D View",default=False,
            description="Export selected objects only")

    def execute(self, context):
        is_2dview = not self.view2d
        self.view2d = is_2dview

        _inline_set_view("2D" if is_2dview else "3D")
        _inline_set_middle_mouse_move(True if is_2dview else False)

        return {'FINISHED'}

def _inline_add_img(path, sprite_name, parent):
    bpy.ops.object.empty_image_add(filepath=path,align="VIEW",name=sprite_name)
    img = bpy.context.object
    img.name = sprite_name
    img.parent = parent
    return img

def _inline_link_object(obj):
    # bpy.context.scene.collection
    active_collection = bpy.context.collection
    active_collection.objects.link(obj)
    return obj

def _inline_selected_edit_bones(edit_bones, selected:bool):
    for edit_bone in edit_bones:
        edit_bone.select = selected
        edit_bone.select_head = selected
        edit_bone.select_tail = selected

class GODOT_2D_BRIDGE_OT_add_plane(Operator):
    bl_label = "According Sprite Add Plane"
    bl_idname = "gd2db.sprite_add_plane"
    bl_options = {'REGISTER', "UNDO"}
    bl_description = "according sprite add plane"

    def execute(self, context: Context):
        active_object = context.view_layer.objects.active

        objects_to_apply = (
                    x for x in context.selected_objects
                    if x.empty_display_type == 'IMAGE'
                )
        
        # create need panel
        for obj in objects_to_apply:
            if not obj.gd2db_object_2d:
                pos = obj.location
                tmp_plane_name = "ms_" + obj.name
                bpy.ops.mesh.primitive_plane_add(location=(0,0, pos[2]))
                tmp_plane = bpy.context.object
                tmp_plane.name = tmp_plane_name
        context.view_layer.objects.active = active_object
        return {'FINISHED'}
    
class GODOT_2D_BRIDGE_OT_add_armature(Operator):
    bl_label = "According Sprite Add Armature"
    bl_idname = "gd2db.sprite_add_armature"
    bl_options = {'REGISTER', "UNDO"}
    bl_description = "according sprite add Armature"

    def execute(self, context: Context):
        # active_object = context.view_layer.objects.active
        objects_to_apply = (
                    x for x in context.selected_objects
                    if x.type == 'MESH' and  "ms_" in x.name 
                )

        for obj in context.selected_objects:
            obj.select_set(False)
        
        # create need armature
        for obj in objects_to_apply:
            if obj.gd2db_object_2d:
                # pos = obj.location
                tmp_name = obj.name.replace("ms_", "ar_")
                loc = obj.location
                if context.active_object != None:
                    bpy.ops.object.mode_set(mode="OBJECT")

                bpy.ops.object.armature_add(
                    radius=1,
                    enter_editmode=True,
                    align="WORLD",
                    location=(loc[0], loc[1], 0),
                    rotation=(0, 0, 0),
                    # rotation=(math.radians(-90), 0, 0),
                )
                
                active_object = bpy.context.active_object
                active_object.name = tmp_name

                armature_object = active_object.data
                armature_object.show_names = True
                # armature_object.dsiplay_fron
                bone_obj = armature_object.edit_bones.active
                bone_obj.tail = (0, 1, 0)
                
        
        # bpy.ops.object.transform_apply(location=False, rotation=True, scale=False, properties=False)
        bpy.ops.object.mode_set(mode='OBJECT')
        # context.view_layer.objects.active = active_object
        return {'FINISHED'}

class   GODOT_2D_BRIDGE_OT_add_bone(Operator):
    bl_label = "Armature Edit Add Bone"
    bl_idname = "gd2db.edit_add_bone"
    bl_options = {'REGISTER', "UNDO"}
    bl_description = "add bone"

    bone_name:StringProperty(default='')

    def execute(self, context):
        # bpy.ops.armature.bone_primitive_add(align='3D_VIEW')
        # bpy.ops.armature.bone_primitive_add()
        
        active_object = context.active_object
        edit_bones = active_object.data.edit_bones
        loc = context.scene.cursor.location - active_object.matrix_world.translation

        tmp_bone_name = 'Bone'
        if self.bone_name != '':
            tmp_bone_name = self.bone_name

        active_edit_bone = edit_bones.active

        edit_bone:bpy.types.EditBone = edit_bones.new(tmp_bone_name)
        edit_bone.head = Vector(loc)
        edit_bone.tail = Vector((loc[0], loc[1] + 1, 0))

        # edit_bone["lock_z"] = True
        # edit_bone["lock_rot"] = True

        tmp_bone_name = edit_bone.name

        if (edit_bones.active != None):
            edit_bone.parent = active_edit_bone

            active_edit_bone.select_head = False
            active_edit_bone.select_tail = False
            active_edit_bone.select = False

        # print("-----tmp_bone_name-------",tmp_bone_name)
        # if tmp_bone_name in active_object.pose.bones:
        #     pose_bone = active_object.pose.bones[tmp_bone_name]
        #     print("-----find-------")
        # #     pose_bone.lock_rotation[0] = True
        # #     pose_bone.lock_rotation[1] = True

        # #     pose_bone.lock_scale[2] = True
        # #     pass

        _inline_selected_edit_bones(edit_bones, False)

        edit_bone.select = True
        edit_bone.select_head = True
        edit_bone.select_tail = True

        return {'FINISHED'}

class   GODOT_2D_BRIDGE_OT_lock_pose_bones(Operator):
    bl_label = "Lock Rot(x,y) Sc(z) Loc(z)"
    bl_idname = "gd2db.lock_pose_bones"
    bl_options = {'REGISTER', "UNDO"}
    bl_description = "Set Bones Lock x,y Rotation/ Lock z Scale"

    def execute(self, context: Context):

        ob = context.active_object
        armature = ob.data
        
        ### lock posebone scale z value
        for bone in armature.bones:
            if bone.name in ob.pose.bones:
                pose_bone = ob.pose.bones[bone.name]
                pose_bone.lock_scale[2] = True

                pose_bone.lock_location[2] = True
                pose_bone.lock_rotation[0] = True
                pose_bone.lock_rotation[1] = True
                   
        return {'FINISHED'}
    
class GODOT_2D_BRIDGE_OT_import_sprites(Operator, ImportHelper):
    bl_label = "Import Sprites"
    bl_idname = "gd2db.import_sprites"
    bl_options = {'REGISTER', "UNDO"}
    bl_description = "Chose json file"

    filter_glob: StringProperty(default="*.json", options={'HIDDEN'})

    def execute(self, context):

        scene_scale = bpy.context.scene.unit_settings.scale_length
        pixels_per_unit = context.scene.godot_2d_bridge_tools.pixels_per_unit
        tmp_scale = 1.0/pixels_per_unit
        tmp_file_path = self.filepath
        tmp_file_path = tmp_file_path.replace("\\", "/")

        # noinspection PyUnresolvedReferences
        data_file = open(tmp_file_path)
        sprite_data = json.load(data_file)
        data_file.close()
        # print(sprite_data)

        ext = os.path.splitext(tmp_file_path)[1]
        folder = os.path.dirname(tmp_file_path)

        for object in bpy.context.selected_objects:
            object.select_set(False)

        sprite_object = context.object
        if not sprite_object:
            bpy.ops.object.empty_add(location=(0,0,0))
            empty_node = bpy.context.object
            sprite_object = empty_node
            
   
        if "name" in sprite_data:
            sprite_object.name = sprite_data["name"]

        if "nodes" in sprite_data:
            for i, sprite in enumerate(sprite_data["nodes"]):
                tmp_sprite_name = sprite["name"]
                tmp_img_filepath = os.path.join(folder, sprite["resource_path"])
                
                pos = [sprite["position"][0], sprite["position"][1], sprite["z"]]
                offset = [sprite["offset"][0], sprite["offset"][1], 0]

                if os.path.exists(tmp_img_filepath):
                    
                    for image in bpy.data.images:
                        if os.path.exists(bpy.path.abspath(image.filepath)) and os.path.exists(tmp_img_filepath):
                            if os.path.samefile(bpy.path.abspath(image.filepath), tmp_img_filepath):
                                img = image
                                img.reload()
                                break

                    if not (tmp_sprite_name in bpy.context.visible_objects):
                        img_obj = None
                        if not (tmp_sprite_name in bpy.data.objects):
                            img_obj = _inline_add_img(tmp_img_filepath, tmp_sprite_name, sprite_object)
                        else:
                            img_obj = bpy.data.objects[tmp_sprite_name]
                            _inline_link_object(img_obj)
                            img_obj.parent = sprite_object

                        img_w, img_h = img_obj.data.size

                        target_phys_widthheight = img_w * tmp_scale
                        final_display_size = (target_phys_widthheight / 2) / scene_scale
                        if img_h > img_w:
                            target_phys_widthheight = img_h * tmp_scale
                            final_display_size = (target_phys_widthheight / 2) / scene_scale

                        pos_offset = (
                            Vector((pos[0], -pos[1], pos[2])) * tmp_scale * 0.5 +
                            Vector((offset[0], offset[1], offset[2])) * tmp_scale * 0.5
                        )
                        pos_offset[2] = pos[2] * tmp_scale

                        img_obj.empty_display_size = final_display_size
                        img_obj.empty_image_offset = [0, -1]
                        img_obj.use_empty_image_alpha = True
                        img_obj.location = pos_offset

                else:
                    print("not found:", tmp_img_filepath)

            # bpy.ops.object.transform_apply(location=False, scale=False, properties=False)
        context.scene.view_layers[0].objects.active = sprite_object

        bpy.ops.view3d.view_axis(type="TOP", align_active=False, relative=False)
        bpy.ops.ed.undo_push(message="Sprite Import")


        return {'FINISHED'}

class GODOT_2D_BRIDGE_OT_export_root(Operator, ExportHelper):
    bl_label = "Godot res:// Path"
    bl_idname = "gd2db.export_root"
    bl_options = {'REGISTER', "UNDO"}
    bl_description = "Chose path res://"

    filename_ext = ""
    filter_glob: StringProperty(default="", options={'HIDDEN'})
    filepath = StringProperty(name="File Path",default="",description="")

    def invoke(self, context: Context, event: Event):
        return super().invoke(context, event)

    def execute(self, context):
        # noinspection PyUnresolvedReferences
        context.scene.godot_2d_bridge_tools.export_root = os.path.dirname(self.filepath)
        return {'FINISHED'}

class GODOT_2D_BRIDGE_OT_export_47(Operator, ExportHelper):
    bl_label = "Export Godot 4.7"
    bl_idname = "gd2db.export_47"
    bl_description = "Export objects to a *.tscn file"

    # set the filename extension and filter for ExportHelper
    filename_ext = ".tscn"
    filter_glob: StringProperty(default="*.tscn", options={'HIDDEN'})

    def execute(self, _context):
        # get the start time of the export process
        export_start_time = perf_counter()

        # use the gd2db_scene_parsing module to write a new *.tscn file
        # noinspection PyUnresolvedReferences
        tmp_root_path = _context.scene.godot_2d_bridge_tools.export_root
        export_success = write_godot_scene_47(tmp_root_path, self.filepath)

        if export_success:
            # parse the list of exported objects
            exported_list = [f"\"{x.name}\"" for x in export_objects()]
            if len(exported_list) == 0:
                custom_message_box(message="Select ObjectS and ArmatureS to Export.",title="Warning!",icon='INFO')
                return
            
            if len(exported_list) > 2:
                exported_list = ", ".join(exported_list[0:-1]), exported_list[-1]
                exported_list = f"{exported_list[0]}, and {exported_list[1]}"
            elif len(exported_list) > 1:
                exported_list = f"{exported_list[0]} and {exported_list[1]}"
            else:
                exported_list = exported_list[0]

            # generate a successful export popup indicating the objects exported and the elapsed time for export process
            custom_message_box(
                message=f"{exported_list} successfully exported in {perf_counter() - export_start_time:05.2f}s.",
                title="Success!",
                icon='INFO'
            )
        return {'FINISHED'}

bl_info = {
    "name": "BlenderPartioTools",
    "description": "Importer for partio files.",
    "author": "Jan Bender",
    "version": (1, 0),
    "blender": (2, 80, 0),
    "warning": "",
    "wiki_url": "https://github.com/InteractiveComputerGraphics/BlenderPartioTools",
    "support": "COMMUNITY",
    "category": "Import-Export"
}


import bpy
import sys
import os
import re
import mathutils
import partio_pybind
from bpy_extras.io_utils import ImportHelper
from bpy.app.handlers import persistent
from bpy.props import StringProperty, BoolProperty, EnumProperty, FloatProperty
from bpy.types import Operator
import numpy as np

class PartioReader:
    def __init__( self, param ):
        self.param = param

    def __call__(self, scene, depsgraph=None):
        partioFile = self.param[0]
        emitterObject = self.param[1]

        try:
            dummy = emitterObject.name
        except:
            # emitter does not exist anymore
            #clear the post frame handler
            bpy.app.handlers.frame_change_post.remove(self)
            return

        indexlist = re.findall(r'\d+', partioFile)
        self.isSequence = True
        if len(indexlist) == 0:
            self.isSequence = False
            fileName = partioFile
        else:
            frameNumber = int(indexlist[-1])
            idx = partioFile.rfind(str(frameNumber))
            l = len(str(frameNumber))
            fileName = str(partioFile[0:idx]) + str(scene.frame_current-1) + str(partioFile[idx+l:])

        print("Read partio file: " + fileName)

        p = partio_pybind.read(fileName)

        cur_frame = scene.frame_current
        start_frame = scene.frame_start
        if cur_frame == start_frame:
            seed = emitterObject.particle_systems[0].seed
            emitterObject.particle_systems[0].seed = seed

        if p != None:
            totalParticles = p.numParticles()
            print("# particles: " + str(totalParticles))

            emitterObject.particle_systems[0].settings.count = totalParticles

            if depsgraph is None:
                depsgraph = bpy.context.evaluated_depsgraph_get()
            particle_systems = emitterObject.evaluated_get(depsgraph).particle_systems
            particles = particle_systems[0].particles

            posAttr = None
            velAttr = None
            for i in range(p.numAttributes()):
                attr=p.attributeInfo(i)
                if attr.name=="position": posAttr = attr
                if attr.name.upper()==emitterObject.partio.color_field: velAttr = attr

            pos = np.array(p.data_buffer(posAttr), copy=True)
            pos[:, [2, 1]] = pos[:, [1, 2]]
            pos[:, 1] = -pos[:, 1]
            world_mat = np.array(emitterObject.matrix_world)
            tpos = np.concatenate([pos, np.ones((p.numParticles(), 1))], axis=1) @ world_mat.T
            pos = tpos[:, :3]

            # Set the location of all particle locations to flatList
            particles.foreach_set("location", pos.ravel())

            if velAttr is not None:
                vel = np.zeros_like(pos)
                vel[:, 0:velAttr.count] = np.array(p.data_buffer(velAttr), copy=True).astype(float)
                if velAttr.name.upper() == "VELOCITY":
                    vel[:, [2, 1]] = vel[:, [1, 2]]
                    vel[:, 1] = -vel[:, 1]
                    tvel = np.concatenate([vel, np.ones((p.numParticles(), 1))], axis=1) @ world_mat.T - np.append(np.array(emitterObject.location), 0)
                    vel = tvel[:, :3]
                particles.foreach_set("velocity", vel.ravel())
                emitterObject.partio.max_velocity = np.max(np.linalg.norm(vel, axis=1))

            emitterObject.particle_systems[0].settings.frame_end = 0
            p.release()


class PartioImporter(Operator, ImportHelper):
    bl_idname = "importer.partio"
    bl_label = "Import partio files"

    filter_glob: StringProperty(
        default="*.bgeo",
        options={'HIDDEN'},
        maxlen=255,
    )

    particleRadius: FloatProperty(
        name="Particle radius",
        description="Particle radius",
        default=0.025,
    )

    maxVel: FloatProperty(
        name="Max. velocity",
        description="Max. velocity",
        default=5.0,
    )

    def execute(self, context):
        self.emitterObject = None
        self.initParticleSystem()

        #run the function on each frame
        param = [self.filepath, self.emitterObject]

        self.emitterObject.partio.file = self.filepath
        self.emitterObject.partio.init = True

        bpy.app.handlers.frame_change_post.append(PartioReader(param))

        scn = bpy.context.scene
        scn.render.engine = 'CYCLES'

        indexlist = re.findall(r'\d+', self.filepath)
        self.isSequence = True
        if len(indexlist) == 0:
            self.isSequence = False
            bpy.context.scene.frame_current = 2
        else:
            frameNumber = int(indexlist[-1])
            bpy.context.scene.frame_current = frameNumber+1

        return {'FINISHED'}

    def initParticleSystem(self):
        # create emitter object
        bpy.ops.mesh.primitive_cube_add(enter_editmode=False, location=(0, 0, 0))

        self.emitterObject = bpy.context.active_object
        self.emitterObject.hide_viewport = False
        self.emitterObject.hide_render = False
        self.emitterObject.hide_select = False

        p = partio_pybind.readHeaders(self.filepath)
        nParticles = p.numParticles()

        # add particle system
        bpy.ops.object.modifier_add(type='PARTICLE_SYSTEM')
        bpy.context.object.show_instancer_for_render = False
        bpy.context.object.show_instancer_for_viewport = False

        self.emitterObject.particle_systems[0].settings.frame_start = 1
        self.emitterObject.particle_systems[0].settings.frame_end = 1
        self.emitterObject.particle_systems[0].settings.lifetime = 1000
        self.emitterObject.particle_systems[0].settings.particle_size = self.particleRadius
        self.emitterObject.particle_systems[0].settings.display_size = 2.0 * self.particleRadius
        if nParticles > 10000:
            self.emitterObject.partio.display_method = 'DOT'
            self.emitterObject.particle_systems[0].settings.display_method = 'DOT'
        else:
            self.emitterObject.partio.display_method = 'RENDER'
            self.emitterObject.particle_systems[0].settings.display_method = 'RENDER'

        self.emitterObject.partio.particle_radius = self.particleRadius

        # add object for rendering particles
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1, enter_editmode=False, location=(0, 0, 0))
        bpy.ops.object.shade_smooth()
        sphereObj = bpy.context.active_object
        sphereObj.hide_set(True)
        sphereObj.hide_viewport = False
        sphereObj.hide_render = True
        sphereObj.hide_select = True

        # add velocity-dependent color material
        found = True
        index = 1
        matNameBase = "ParticleMaterial"
        matName = matNameBase + str(index)
        materials = bpy.data.materials
        while (found):
            material = materials.get( matName )
            if material:
                index += 1
                matName = matNameBase + str(index)
            else:
                found = False

        material = materials.new( matName )


        material.use_nodes = True
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        nodes.clear()
        links.clear()
        output = nodes.new( type = 'ShaderNodeOutputMaterial' )
        diffuse = nodes.new( type = 'ShaderNodeBsdfDiffuse' )
        link = links.new( diffuse.outputs['BSDF'], output.inputs['Surface'] )

        particleInfo = nodes.new( type = 'ShaderNodeParticleInfo' )

        vecMath = nodes.new( type = 'ShaderNodeVectorMath' )
        vecMath.operation = 'DOT_PRODUCT'

        math1 = nodes.new( type = 'ShaderNodeMath' )
        math1.operation = 'SQRT'
        math2 = nodes.new( type = 'ShaderNodeMath' )
        math2.operation = 'MULTIPLY'
        math2.inputs[1].default_value = 1.0/self.maxVel
        math2.use_clamp = True


        ramp = nodes.new( type = 'ShaderNodeValToRGB' )
        ramp.color_ramp.elements[0].color = (0, 0, 1, 1)

        link = links.new( particleInfo.outputs['Velocity'], vecMath.inputs[0] )
        link = links.new( particleInfo.outputs['Velocity'], vecMath.inputs[1] )

        link = links.new( vecMath.outputs['Value'], math1.inputs[0] )
        link = links.new( math1.outputs['Value'], math2.inputs[0] )
        link = links.new( math2.outputs['Value'], ramp.inputs['Fac'] )
        link = links.new( ramp.outputs['Color'], diffuse.inputs['Color'] )

        self.emitterObject.active_material = material
        sphereObj.active_material = material

        self.emitterObject.particle_systems[0].settings.render_type = 'OBJECT'
        self.emitterObject.particle_systems[0].settings.instance_object = bpy.data.objects[sphereObj.name]


def getColorFields(self, context):
    pheader = partio_pybind.readHeaders(self.file)
    enum_items = [("NONE", "None", "No Coloring", 0)]
    if pheader is not None:
        for i in range(pheader.numAttributes()):
            attr = pheader.attributeInfo(i)
            enum_items.append((attr.name.upper(), attr.name, "", i+1))

    return enum_items


def updateEnum(self, context):
    param = [self.file, context.object]
    PartioReader(param)(context.scene)
    if context is not None:
        scaling_node = context.object.active_material.node_tree.nodes.get('Math.001').inputs[1]
        scaling_node.default_value = 1. / self.max_velocity


def updateParticleRadius(self, context):
    cur_obj = context.object
    for particle_system in cur_obj.particle_systems:
        particle_system.settings.particle_size = self.particle_radius
        particle_system.settings.display_size = 2.0 * self.particle_radius


def updateDisplayMethod(self, context):
    cur_obj = context.object
    for particle_system in cur_obj.particle_systems:
        particle_system.settings.display_method = self.display_method


class PartioReinitOperator(bpy.types.Operator):
    """Tooltip"""
    bl_idname = "object.reinit_partio"
    bl_label = "Reinit partio loading"

    @classmethod
    def poll(cls, context):
        return context.active_object.partio.init

    def execute(self, context):
        keep_callbacks = []
        for callback in bpy.app.handlers.frame_change_post:
            if not isinstance(callback, PartioReader):
                keep_callbacks.append(callback)
        
        for obj in bpy.data.objects:
            if obj.partio.init:
                param = [obj.partio.file, obj]
                keep_callbacks.append(PartioReader(param))

        bpy.app.handlers.frame_change_post.clear()
        for callback in keep_callbacks:
            bpy.app.handlers.frame_change_post.append(callback)

        return {'FINISHED'}


class PartioParameters(bpy.types.PropertyGroup):
    file: bpy.props.StringProperty(name="Partio File", subtype='FILE_PATH')
    init: bpy.props.BoolProperty(name="Initialized", default=False)
    color_field: bpy.props.EnumProperty(name="Color", items=getColorFields, update=updateEnum)
    max_velocity: bpy.props.FloatProperty(name="Max Value of Color Field", default=1.)
    particle_radius: bpy.props.FloatProperty(name="Particle Radius", default=0.025, update=updateParticleRadius)
    display_method: bpy.props.EnumProperty(items=[('DOT', 'Point', 'Render as point', 0),
                                                  ('RENDER', 'Object', 'Render as instanced object', 1)],
                                           name="Display Method", update=updateDisplayMethod)


class PartioPanel(bpy.types.Panel):
    """Creates a Panel in the Object properties window"""
    bl_label = "Partio Settings"
    bl_idname = "OBJECT_PT_partio"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        return context.object.partio.init

    def draw(self, context):
        layout = self.layout

        obj = context.object

        row = layout.row()
        row.prop(obj.partio, "file")

        row = layout.row()
        row.prop(obj.partio, "init")

        row = layout.row()
        row.prop(obj.partio, "color_field")

        row = layout.row()
        row.prop(obj.partio, "display_method")

        row = layout.row()
        row.prop(obj.partio, "max_velocity")

        row = layout.row()
        row.prop(obj.partio, "particle_radius")

        row = layout.row()
        row.operator("object.reinit_partio")


@persistent
def loadPost(scene):
    for obj in bpy.data.objects:
        if obj.partio.init:
            param = [obj.partio.file, obj]
            bpy.app.handlers.frame_change_post.append(PartioReader(param))


# Only needed if you want to add into a dynamic menu
def menu_func_import(self, context):
    self.layout.operator(PartioImporter.bl_idname, text="Partio Import")


def register():
    bpy.utils.register_class(PartioImporter)
    bpy.utils.register_class(PartioParameters)
    bpy.utils.register_class(PartioPanel)
    bpy.utils.register_class(PartioReinitOperator)
    bpy.types.Object.partio = bpy.props.PointerProperty(type=PartioParameters)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.app.handlers.load_post.append(loadPost)
    print(bpy.app.handlers.load_post)


def unregister():
    bpy.utils.unregister_class(PartioImporter)
    bpy.utils.unregister_class(PartioParameters)
    bpy.utils.unregister_class(PartioPanel)
    bpy.utils.unregister_class(PartioReinitOperator)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.app.handlers.load_post.remove(loadPost)


if __name__ == "__main__":
    print ("main")
    register()

    # test call
    bpy.ops.importer.partio('INVOKE_DEFAULT')
    unregister()
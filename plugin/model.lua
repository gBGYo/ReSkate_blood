local V=require("math3")
local Tracker=require("impacts")
local Particles=require("particles")
local Ground=require("ground")
local Model={}
Model.__index=Model
Model.defaults={enabled=false,reduced=false,strength=1,minimum_damage=25,density=1,width=1,length=1,bleeding=1,lifetime=90,color=1}
local ranges={strength={0,1},minimum_damage={0,3600},density={.25,3},width={.25,3},length={.25,3},bleeding={.25,5},lifetime={10,300},color={1,4}}
function Model.options(saved)
    local options=table.clone(Model.defaults)
    if type(saved)~="table" then return options end
    for key,default in options do
        local value=saved[key]
        if type(default)=="boolean" then
            if type(value)=="boolean" then options[key]=value end
        else
            local range=ranges[key]
            if type(value)=="number" and value>=range[1] and value<=range[2] and (key~="color" or value%1==0) then options[key]=value end
        end
    end
    return options
end
function Model.new(api)
    return setmetatable({api=api,tracker=Tracker.new(),particles=Particles.new(api),ground=Ground.new(api),samples=0,hits=0},Model)
end
function Model:clear()
    -- The native epoch may already have released the handles; clear is idempotent.
    self.api.clear()
    self.tracker:clear()
    self.particles=Particles.new(self.api); self.ground=Ground.new(self.api)
    self.last_at,self.center=nil,nil
end
function Model:step(event,o)
    if not o.enabled or o.strength<=0 then return end
    local f=V.frame(event)
    if not f then self:clear(); return end
    if self.last_at and (f.at-self.last_at>250 or f.at<self.last_at) then self:clear() end
    if self.center and vector.magnitude(f.center-self.center)>math.max(2,vector.magnitude(f.bodies.Pelvis.velocity)*f.dt*3) then self:clear() end
    self.last_at,self.center=f.at,f.center
    local hits=self.tracker:step(f)
    self.samples+=1; self.hits+=#hits
    self.particles:step(f,hits,o); self.ground:step(f,hits,o)
end
function Model:render() self.ground:render() end
return Model

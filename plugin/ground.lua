local V = require("math3")
local Ground = {}
Ground.__index = Ground
local colors={"","_green","_blue","_pink"}
local variants={"","_broken","_clotted","_drop"}
local function cell(x,y,z) return x..":"..y..":"..z end
local function surface(b)
    return b and b.contact and b.normal and b.point and not b.board and
        vector.magnitude(b.normal)>.5 and vector.magnitude(b.normal)<1.5 and
        vector.magnitude(V.axis(b.pose,13)-b.point)<1
end
local function torso(f)
    local support
    for name,b in f.bodies do
        if V.torso(name) and surface(b) and (not support or support.name=="Pelvis" or name<support.name) then support=b end
    end
    if not support then return nil end
    local normal=V.unit(support.normal)
    local point,position,velocity,weight=V.zero,V.zero,V.zero,0
    for name,b in f.bodies do
        if not V.torso(name) or not surface(b) or b.vehicle~=support.vehicle or vector.dot(V.unit(b.normal),normal)<.9 then continue end
        local separation=b.point-support.point
        if math.abs(vector.dot(separation,normal))>.06 or vector.magnitude(separation)>.9 then continue end
        local at=V.axis(b.pose,13)
        local offset=at-b.point
        offset-=normal*vector.dot(offset,normal)
        if vector.magnitude(offset)>.3 then offset=V.unit(offset)*.3 end
        local contribution=name=="Pelvis" and .6 or 1
        point+=(b.point+offset)*contribution; position+=at*contribution
        velocity+=b.velocity*contribution; weight+=contribution
    end
    local out=table.clone(support)
    out.pose=table.clone(support.pose)
    out.point=point/weight; out.normal=normal; out.velocity=velocity/weight
    position/=weight; out.pose[13]=position.x; out.pose[14]=position.y; out.pose[15]=position.z
    return out
end
local function random(w)
    local x=w.random
    x=bit32.bxor(x,bit32.lshift(x,13)); x=bit32.bxor(x,bit32.rshift(x,17)); x=bit32.bxor(x,bit32.lshift(x,5))
    w.random=x
    return bit32.rshift(x,8)/16777216
end
local function alpha(m)
    return math.min(math.clamp((m.lifetime-m.age)/5,0,1),m.retirement and math.clamp(m.retirement/2,0,1) or 1)
end
local function overlap(a,b)
    local delta=a.point-b.point
    if vector.dot(a.normal,b.normal)<.95 or math.abs(vector.dot(delta,a.normal))>.025 or math.abs(vector.dot(delta,b.normal))>.025 then return false end
    for _,axis in {V.unit(a.x),V.unit(a.z),V.unit(b.x),V.unit(b.z)} do
        if math.abs(vector.dot(delta,axis))>=.375*(math.abs(vector.dot(a.x,axis))+math.abs(vector.dot(a.z,axis))+
            math.abs(vector.dot(b.x,axis))+math.abs(vector.dot(b.z,axis))) then return false end
    end
    return true
end
function Ground.new(api) return setmetatable({api=api,marks={},cells={},largest=0,wounds={},episodes={},spawned=0,retired=0},Ground) end
function Ground:clear()
    for _,m in self.marks do self.api.release(m.handle) end
    self.marks,self.cells,self.wounds,self.episodes,self.largest={},{},{},{},0
end
function Ground:unindex(m)
    local list=self.cells[m.cell]
    if not list then return end
    local i=table.find(list,m)
    if i then table.remove(list,i) end
    if #list==0 then self.cells[m.cell]=nil end
end
function Ground:crowded(m)
    local p=m.point
    local reach=m.radius+self.largest+.025
    local count=0
    for x=math.floor(p.x-reach),math.floor(p.x+reach) do
        for y=math.floor(p.y-reach),math.floor(p.y+reach) do
            for z=math.floor(p.z-reach),math.floor(p.z+reach) do
                for _,other in self.cells[cell(x,y,z)] or {} do
                    if alpha(other)<.5 or (m.impact and not other.impact) or (m.kind==5)~=(other.kind==5) or (m.kind==4)~=(other.kind==4) then continue end
                    if overlap(m,other) then count+=1; if count>=3 then return true end end
                end
            end
        end
    end
    return false
end
function Ground:retire()
    if #self.marks-self.retiring<1792 then return end
    local victim,best=nil,-1
    for _,m in self.marks do
        if m.retirement or m.age<(m.impact and 10 or 5) then continue end
        local far=vector.magnitude(m.point-self.focus)>20
        local score=(far and 1000 or 0)+(m.impact and 0 or m.kind==4 and 300 or m.kind==5 and 100 or 200)+m.age
        if score>best then best=score; victim=m end
    end
    if victim then victim.retirement=2; self.retiring+=1 end
end
function Ground:stamp(point,normal,direction,width,length,kind,variant,impact,vehicle)
    if kind==4 and #self.marks>=1536 then return end
    local right=V.tangent(direction,normal)
    local shallow=vehicle or normal.y<=.5
    local depth=shallow and .08 or kind==5 and .55 or .24
    local lift=shallow and .015 or kind==5 and .12 or .04
    local x,z=right*length*1.15,vector.cross(right,normal)*width*1.15
    local m={point=point,normal=normal,x=x,z=z,radius=.5*math.sqrt(vector.dot(x,x)+vector.dot(z,z)),
        kind=kind,impact=impact,age=0,lifetime=self.options.lifetime,opacity=255}
    if self:crowded(m) then return end
    self:retire()
    if #self.marks>=(impact and 2048 or 1920) then return end
    local material="world/materials/decal/reskate_blood/reskate_blood"..variants[kind==5 and variant or kind]..colors[self.options.color].."_dv"
    m.handle=self.api.decal(material,V.matrix(x,normal*depth,z,point+normal*lift),{attach=true,lift=lift})
    if not m.handle then return end
    m.cell=cell(math.floor(point.x),math.floor(point.y),math.floor(point.z))
    self.cells[m.cell]=self.cells[m.cell] or {}
    table.insert(self.cells[m.cell],m); table.insert(self.marks,m)
    self.largest=math.max(self.largest,m.radius); self.spawned+=1
end
function Ground:deposit(w,point,normal,direction,width,initial)
    local o=self.options
    local r=table.create(10)
    for i=1,10 do r[i]=random(w) end
    local stretched=w.torso and not initial and r[2]<.42
    local length=w.torso and (stretched and .36+.19*r[7] or .16+.16*r[7]) or initial and .13+.08*r[7] or .09+.21*r[7]
    w.spacing=(w.torso and ((.14+.6*length+.14*r[1])*(r[1]<.3 and .5 or 1)+(r[9]<.16 and .14 or 0)) or
        .055+.105*r[1]+(r[2]<.16 and .11 or 0))*(o.reduced and 1.8 or 1)/o.density
    if w.torso then
        local choice=math.floor(r[5]*(w.variant and 2 or 3))
        w.variant=w.variant and (w.variant+choice)%3+1 or choice+1
    end
    direction=V.tangent(direction,normal)
    local side=vector.cross(direction,normal)
    local angle=(r[3]-.5)*.7+(w.torso and r[10]<.5 and math.pi or 0)
    point+=side*(r[4]-.5)*(w.torso and .075 or .05)
    local axis=direction*math.cos(angle)+side*math.sin(angle)
    if self.budget>0 then
        local response=V.response(w.severity)
        local scale=initial and response.stain or response.trail
        local breadth=width*(w.torso and (stretched and .6+.35*r[6] or .8+.35*r[6]) or .5+r[6])
        self:stamp(point,normal,axis,breadth*scale*o.width,length*scale*o.length,w.torso and 5 or math.min(3,math.floor(r[5]*3)+1),w.variant,initial,w.vehicle)
        self.budget-=1
    end
    if not initial and not o.reduced and r[8]<(w.torso and .2 or .6) and self.budget>0 then
        local lateral=(r[9]<.5 and -1 or 1)*(w.torso and width*(.28+.14*r[10]) or .035+.075*r[10])
        point+=side*lateral-direction*.025
        local size=.025+.04*r[9]
        self:stamp(point,normal,side,size,size*(.8+.4*r[10]),4,1,false,w.vehicle); self.budget-=1
    end
end
function Ground:step(f,hits,o)
    self.options,self.focus,self.retiring=o,f.center,0
    for i=#self.marks,1,-1 do
        local m=self.marks[i]; m.age+=f.dt
        if m.retirement then m.retirement-=f.dt; self.retiring+=1 end
        if m.age>=m.lifetime or (m.retirement and m.retirement<=0) then
            self:unindex(m); self.api.release(m.handle); table.remove(self.marks,i)
            if m.retirement then self.retiring-=1; self.retired+=1 end
        end
    end
    if not f.bailed then self.wounds,self.episodes={},{}; return end
    for key,w in self.wounds do w.remaining-=f.dt; if w.remaining<=0 then self.wounds[key]=nil end end
    for _,hit in hits do
        if hit.severity<o.minimum_damage or hit.body.board or self.episodes[hit.name]==hit.episode then continue end
        self.episodes[hit.name]=hit.episode
        local broad=V.torso(hit.name)
        local key=broad and "torso" or hit.name
        local w=self.wounds[key]
        if not w then
            w={name=hit.name,torso=broad,random=bit32.bxor(bit32.band(hit.episode*2654435761,0xffffffff),#hit.name*2246822519),
                severity=0,remaining=0,distance=0,spacing=.1}
            if w.random==0 then w.random=1 end
            self.wounds[key]=w
        end
        w.severity=math.max(w.severity,hit.severity)
        w.remaining=math.max(w.remaining,V.response(hit.severity).seconds*o.bleeding)
        w.pending=true
    end
    self.budget=o.reduced and 2 or 6
    local ordered={}
    for key,w in self.wounds do table.insert(ordered,{key=key,w=w,initial=not w.tracking or w.pending}) end
    table.sort(ordered,function(a,b)
        if not not a.initial~=not not b.initial then return not not a.initial end
        if not not a.w.torso~=not not b.w.torso then return not not a.w.torso end
        return a.key<b.key
    end)
    local footprint=torso(f)
    for _,entry in ordered do
        local w=entry.w
        local b=w.torso and footprint or f.bodies[w.name]
        if not surface(b) then w.tracking=false; w.distance=0; continue end
        if w.tracking and w.vehicle~=b.vehicle then w.tracking=false; entry.initial=true end
        w.vehicle=b.vehicle
        local point,normal,at=b.point,V.unit(b.normal),V.axis(b.pose,13)
        local delta=w.point and point-w.point or V.zero
        local distance=vector.magnitude(delta)
        if w.tracking and vector.magnitude(at-w.position)>1.5 then self.wounds[entry.key]=nil; continue end
        local width=w.torso and .40+.08*o.strength or (.09+.055*o.strength)*((w.name=="Head" or w.name=="Neck") and 1.1 or .8)
        if entry.initial then
            if self.budget==0 then continue end
            self:deposit(w,point,normal,b.velocity,width,true); w.distance=0; w.pending=false
        elseif distance>.7 or vector.dot(normal,w.normal)<.85 or math.abs(vector.dot(delta,normal))>.035+distance*.04 then
            w.distance=0
        elseif distance>.00001 then
            local direction=delta/distance
            local travel=w.spacing-w.distance
            while travel<=distance do
                self:deposit(w,w.point+direction*travel,normal,direction,width,false)
                travel+=w.spacing
            end
            w.distance=math.max(0,w.spacing-(travel-distance))
        end
        w.point,w.normal,w.position,w.tracking=point,normal,at,true
    end
end
function Ground:render()
    for _,m in self.marks do
        local value=math.floor(alpha(m)*255+.5)
        if value~=m.opacity then self.api.opacity(m.handle,value/255); m.opacity=value end
    end
end
return Ground

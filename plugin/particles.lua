local V = require("math3")
local Particles = {}
Particles.__index = Particles
local names = {"spray", "droplets", "trail"}
local colors = {"", "_green", "_blue", "_pink"}
function Particles.new(api) return setmetatable({api=api, sources={}, episodes={}}, Particles) end
function Particles:clear()
    for _,s in self.sources do if s.handle then self.api.release(s.handle) end end
    self.sources, self.episodes = {}, {}
end
function Particles:step(f, hits, o)
    if not f.bailed then self.episodes={} end
    local limit = o.reduced and 6 or 24
    for i = #self.sources, 1, -1 do
        local s = self.sources[i]
        s.age += f.dt
        if s.age >= s.lifetime or i > limit then
            if s.handle then self.api.release(s.handle) end
            table.remove(self.sources,i)
        else
            local emitting = f.bailed and s.age<s.emit and not (o.reduced and s.kind~=1)
            local b = f.bodies[s.name]
            if emitting and s.kind~=1 then
                if not b then emitting=false else
                    local at = V.point(b.pose,s.point)
                    if vector.magnitude(at-V.axis(s.transform,13))>2 then emitting=false else
                        s.transform=V.transform(at,V.direction(b.pose,s.direction),s.scale)
                        if s.handle then self.api.move(s.handle,s.transform) end
                    end
                end
            end
            if not emitting and not s.stopped then
                s.stopped=true; if s.handle then self.api.stop(s.handle) end
            end
        end
    end
    if not f.bailed then return end
    local bursts=0
    for _,hit in hits do
        local b=hit.body
        if hit.severity<o.minimum_damage or self.episodes[hit.name]==hit.episode or b.board or not b.normal then continue end
        self.episodes[hit.name]=hit.episode
        bursts+=1
        if bursts>2 then continue end
        local wounds, already = 0,false
        for _,s in self.sources do
            if s.kind==3 and not s.stopped then wounds+=1; already=already or s.name==hit.name end
        end
        if already or wounds>=2 then continue end
        local at=(b.point or V.axis(b.pose,13))+.015*V.unit(b.normal)
        local normal=V.unit(b.normal)
        local direction=normal+.035*(hit.incoming-vector.dot(hit.incoming,normal)*normal)
        local response=V.response(hit.severity)
        local tier=hit.severity<100 and "_light" or hit.severity>=324 and not o.reduced and "_heavy" or ""
        for kind,name in names do
            if #self.sources>=limit then break end
            if o.reduced and kind~=1 then continue end
            local scale=(.3+.9*o.strength)*(kind==1 and response.spray or response.drop)
            local transform=V.transform(at,direction,scale)
            local emit=kind==1 and .12 or (kind==2 and .5 or .7)*response.emission
            local handle=self.api.particle("effects/reskate/gbgyo_blood/ebp_blood_"..name..tier..colors[o.color],transform)
            if handle then table.insert(self.sources,{handle=handle,kind=kind,name=hit.name,transform=transform,
                point=V.local_point(b.pose,at),direction=V.local_direction(b.pose,V.unit(direction)),scale=scale,
                emit=emit,lifetime=emit+(kind==2 and .8 or .5),age=0}) end
        end
    end
end
return Particles

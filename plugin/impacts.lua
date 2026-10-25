local V = require("math3")
local Tracker = {}
Tracker.__index = Tracker
function Tracker.new() return setmetatable({episodes={}, recent={}, angular={}, serial=0}, Tracker) end
function Tracker:clear()
    self.episodes, self.recent, self.angular, self.previous = {}, {}, {}, nil
end
local function turning(before, body, dt)
    local angular, trace = V.zero, 0
    for i = 1, 9, 4 do
        local a, b = V.axis(before.pose,i), V.axis(body.pose,i)
        angular += vector.cross(a,b)/(2*dt)
        trace += vector.dot(a,b)
    end
    return trace >= 2 and vector.magnitude(angular) <= 100 and angular or nil
end
function Tracker:step(f)
    local before = self.previous
    if not before then
        if f.bailed then return {} end -- Starting halfway through a fall never invents an impact.
        self.previous = f
        for name,b in f.bodies do self.episodes[name] = {blocked=b.contact, remaining=.2, speed=0} end
        return {}
    end
    local speed = 0
    for _, b in f.bodies do speed = math.max(speed, vector.magnitude(b.velocity)) end
    if vector.magnitude(f.center-before.center) > math.max(2, speed*f.dt*3) then self:clear(); return {} end
    if before.bailed and not f.bailed then self:clear(); return self:step(f) end
    local hits, angles = {}, {}
    for name, body in f.bodies do
        local old = before.bodies[name]
        local episode = self.episodes[name] or {blocked=body.contact, remaining=.2, speed=0}
        self.episodes[name] = episode
        local recent = self.recent[name]
        if recent then
            recent.remaining -= f.dt
            if recent.remaining <= 0 then self.recent[name] = nil; recent = nil end
        end
        local native = body.contact and body.normal and type(body.speed)=="number" and body.speed==body.speed and body.speed>=0 and body.speed<=300
        local native_hit = native and body.speed>=3 and not body.board
        if not body.contact or (native and not native_hit) then
            episode.remaining = math.max(0, episode.remaining-f.dt)
            if (not episode.native and not native) or episode.remaining <= .00001 then
                episode = {remaining=0, speed=0}; self.episodes[name] = episode
            end
        elseif native_hit or not episode.native then episode.remaining=.2 end
        episode.native = episode.native or native
        if old and before.bailed and f.bailed then angles[name]=turning(old,body,f.dt) end
        local hit
        if old and body.contact and body.normal and not body.board and not episode.blocked then
            local normal = V.unit(body.normal)
            local change = native and body.speed or 0
            -- Rotation at the contact contributes only with two measured, unambiguous turns.
            if episode.speed==0 and body.point and angles[name] and self.angular[name] then
                local lever = body.point-V.axis(body.pose,13)
                local previous_lever = body.point-V.axis(old.pose,13)
                if vector.magnitude(lever)<=1.5 and vector.magnitude(previous_lever)<=1.5 then
                    local incoming = vector.cross(self.angular[name],previous_lever)
                    local outgoing = vector.cross(angles[name],lever)
                    if -vector.dot(incoming,normal)>=2 then change=math.max(change,vector.dot(outgoing-incoming,normal)) end
                end
            end
            if change>=3 and change>episode.speed then
                episode.speed=change; episode.remaining=.2
                if not episode.id then self.serial+=1; episode.id=self.serial end
                hit={name=name, body=body, incoming=old.velocity, episode=episode.id, severity=math.min(60,change)^2}
                if not before.bailed and not f.bailed then
                    self.recent[name]={hit=hit, remaining=.2}; hit=nil
                end
            end
        end
        if f.bailed and not before.bailed and recent then
            if not hit or recent.hit.severity>hit.severity then hit=recent.hit end
            self.recent[name]=nil
        end
        if hit and f.bailed then table.insert(hits, hit) end
    end
    table.sort(hits, function(a,b) return a.severity==b.severity and a.name<b.name or a.severity>b.severity end)
    self.previous, self.angular = f, angles
    return hits
end
return Tracker

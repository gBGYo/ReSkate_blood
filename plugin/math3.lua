local M = {}
M.zero = vector.create(0, 0, 0)
M.up = vector.create(0, 1, 0)
function M.vec(v)
    if type(v) == "vector" then return v end
    if type(v) ~= "table" then return nil end
    for i = 1, 3 do
        if type(v[i]) ~= "number" or v[i] ~= v[i] or math.abs(v[i]) > 100000 then return nil end
    end
    return vector.create(v[1], v[2], v[3])
end
function M.axis(m, n) return vector.create(m[n], m[n + 1], m[n + 2]) end
function M.unit(v, fallback)
    local length = vector.magnitude(v)
    return length > 0.0001 and v / length or fallback or M.up
end
function M.tangent(v, normal)
    v -= normal * vector.dot(v, normal)
    if vector.magnitude(v) < 0.0001 then
        v = math.abs(normal.x) < .8 and vector.create(1, 0, 0) or vector.create(0, 0, 1)
        v -= normal * vector.dot(v, normal)
    end
    return M.unit(v)
end
function M.matrix(x, y, z, at)
    return {x.x,x.y,x.z,0, y.x,y.y,y.z,0, z.x,z.y,z.z,0, at.x,at.y,at.z,1}
end
function M.transform(at, up, scale)
    up = M.unit(up)
    local right = M.unit(vector.cross(math.abs(up.y) < .9 and M.up or vector.create(0, 0, 1), up))
    return M.matrix(right * scale, up * scale, vector.cross(right, up) * scale, at)
end
function M.direction(m, v) return M.axis(m, 1)*v.x + M.axis(m, 5)*v.y + M.axis(m, 9)*v.z end
function M.point(m, v) return M.axis(m, 13) + M.direction(m, v) end
function M.local_direction(m, v)
    return vector.create(vector.dot(v, M.axis(m, 1)), vector.dot(v, M.axis(m, 5)), vector.dot(v, M.axis(m, 9)))
end
function M.local_point(m, v) return M.local_direction(m, v - M.axis(m, 13)) end
function M.pose(m)
    if type(m) ~= "table" or #m ~= 16 then return false end
    for _, n in m do if type(n) ~= "number" or n ~= n or math.abs(n) > 100000 then return false end end
    for a = 1, 9, 4 do
        if math.abs(vector.dot(M.axis(m,a), M.axis(m,a)) - 1) > .05 then return false end
        for b = 1, a - 1, 4 do if math.abs(vector.dot(M.axis(m,a), M.axis(m,b))) > .05 then return false end end
    end
    return true
end
function M.response(damage)
    local speed = math.sqrt(math.clamp(damage, 0, 3600))
    local r = speed < 12 and math.clamp((speed-12)/7, -1, 0) or math.clamp((speed-12)/13, 0, 1)
    return {spray = 1+r*(r<0 and .2 or 1.28), drop = 1+.35*math.max(0,r),
        emission = 1+r*(r<0 and .65 or 1), stain = 1+r*(r<0 and .35 or 2.456),
        trail = 1+r*(r<0 and .2 or 1), seconds = 8+r*(r<0 and 5 or 4)}
end
function M.torso(name)
    return name == "Pelvis" or name == "Spine" or name == "Lower back" or name == "Chest" or name == "Upper chest"
end
function M.frame(e)
    if type(e.seconds) ~= "number" or not (e.seconds > 0 and e.seconds <= .1) then return nil end
    local f = {dt=e.seconds, bailed=e.wipeout or e.state == 300 or e.ragdoll == true, bodies={}, at=e.at}
    for name, pose in e.poses or {} do
        if M.pose(pose.transform) then
            local velocity = M.vec(pose.velocity)
            if velocity and vector.magnitude(velocity) <= 300 then
                local contact = (e.bodies or {})[name]
                f.bodies[name] = {name=name, pose=pose.transform, velocity=velocity, contact=contact ~= nil,
                    point=contact and M.vec(contact.point), normal=contact and M.vec(contact.normal),
                    speed=contact and contact.impact, vehicle=contact and contact.vehicle,
                    board=contact and contact.board and not contact.vehicle and not contact.world}
            end
        end
    end
    local pelvis = f.bodies.Pelvis
    if not pelvis then return nil end
    f.center = M.axis(pelvis.pose, 13)
    return f
end
return M

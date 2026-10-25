local Model=require("model")
local V=require("math3")
local function recorder()
    local r={serial=0,live={},particles=0,decals=0,stopped=0,faded=0,released=0}
    local api={}
    local function make(asset,matrix,kind,options)
        r.serial+=1; r.live[r.serial]={asset=asset,matrix=matrix,kind=kind,options=options}
        r[kind]+=1; return r.serial
    end
    api.particle=function(asset,matrix) return make(asset,matrix,"particles") end
    api.decal=function(asset,matrix,options) return make(asset,matrix,"decals",options) end
    api.move=function(id,matrix) assert(r.live[id]); r.live[id].matrix=matrix end
    api.stop=function(id) assert(r.live[id]); r.stopped+=1 end
    api.opacity=function(id,value) assert(r.live[id] and value>=0 and value<=1); r.faded+=1 end
    api.release=function(id) assert(r.live[id]); r.live[id]=nil; r.released+=1 end
    api.clear=function() r.live={} end
    return r,api
end
local function event(at,bailed,speed,x,board,wall)
    local p=vector.create(x or 0,.15,0)
    local pose=V.matrix(vector.create(1,0,0),V.up,vector.create(0,0,1),p)
    local bodies={}
    if speed then bodies["Left forearm"]={impact=speed,normal=wall and {1,0,0} or {0,1,0},point={x or 0,0,0},board=board,world=not board,vehicle=wall} end
    return {at=at,seconds=.05,wipeout=bailed,ragdoll=bailed,bodies=bodies,
        poses={Pelvis={transform=pose,velocity={5,-(speed or 0),0}},["Left forearm"]={transform=pose,velocity={5,-10,0}}}}
end
return {run=function()
    local passed=0
    local function test(name,f)
        local ok,why=pcall(f)
        assert(ok,name..": "..tostring(why)); passed+=1
    end
    local function fresh()
        local r,api=recorder(); local m=Model.new(api); local o=Model.options({enabled=true})
        m:step(event(0,false,nil),o)
        return r,m,o
    end
    test("off by default and corrupt preferences",function()
        local o=Model.options({enabled="yes",color=9,width=0/0,lifetime=0})
        assert(not o.enabled and o.color==1 and o.width==1 and o.lifetime==90)
    end)
    test("confirmed impact creates three sources and a bound stain",function()
        local r,m,o=fresh(); m:step(event(50,true,12),o)
        assert(r.particles==3 and r.decals==1)
        for _,e in r.live do if e.kind=="decals" then assert(e.options.attach and e.options.lift>0) end end
    end)
    test("gravity and animation without contact do not bleed",function()
        local r,m,o=fresh(); for i=1,8 do m:step(event(i*50,true,nil),o) end
        assert(r.particles==0 and r.decals==0)
    end)
    test("board-only contacts are refused",function()
        local r,m,o=fresh(); m:step(event(50,true,20,0,true),o); assert(r.serial==0)
    end)
    test("damage threshold",function()
        local r,m,o=fresh(); o.minimum_damage=401; m:step(event(50,true,20),o); assert(r.serial==0)
    end)
    test("held and rising contacts are one wound",function()
        local r,m,o=fresh()
        for i=1,8 do m:step(event(i*50,true,10+i),o) end
        assert(r.particles==3 and r.decals==1)
    end)
    test("a pre-bail contact is retained",function()
        local r,m,o=fresh(); m:step(event(50,false,12),o); assert(r.serial==0)
        m:step(event(100,true,0),o); assert(r.particles==3 and r.decals==1)
    end)
    test("recovery rearms while keeping stains",function()
        local r,m,o=fresh(); m:step(event(50,true,12),o)
        m:step(event(100,false,nil),o); assert(#m.ground.marks==1 and r.stopped==3)
        m:step(event(150,true,12,.3),o); assert(r.particles==6)
    end)
    test("teleports clear old effects",function()
        local r,m,o=fresh(); m:step(event(50,true,12),o); m:step(event(100,true,12,20),o)
        assert(next(r.live)==nil and #m.ground.marks==0)
    end)
    test("starting mid-fall does not invent a hit",function()
        local r,api=recorder(); local m=Model.new(api)
        m:step(event(50,true,20),Model.options({enabled=true})); assert(r.serial==0)
    end)
    test("reduced mode and color",function()
        local r,m,o=fresh(); o.reduced=true; o.color=4; m:step(event(50,true,25),o)
        assert(r.particles==1 and r.decals==1)
        for _,e in r.live do assert(e.asset:find("_pink")) end
    end)
    test("wall and vehicle stains retain the shallow projector",function()
        local r,m,o=fresh(); m:step(event(50,true,12,0,false,true),o)
        assert(r.decals==1)
        for _,e in r.live do if e.kind=="decals" then assert(math.abs(vector.magnitude(V.axis(e.matrix,5))-.08)<.0001) end end
    end)
    test("sliding leaves irregular spaced smears",function()
        local r,m,o=fresh(); m:step(event(50,true,12),o)
        for i=2,15 do m:step(event(i*50,true,0,i*.08),o) end
        assert(r.decals>3 and r.decals<40 and r.particles==3)
    end)
    test("lifetime fades and releases marks",function()
        local r,m,o=fresh(); o.lifetime=10; m:step(event(50,true,12),o)
        for i=2,203 do m:step(event(i*50,false,nil),o); m:render() end
        assert(r.faded>0 and next(r.live)==nil and #m.ground.marks==0)
    end)
    test("missing renderer never queues old effects",function()
        local r,api=recorder(); api.particle=function() return nil end; api.decal=function() return nil end
        local m=Model.new(api); local o=Model.options({enabled=true})
        m:step(event(0,false,nil),o); m:step(event(50,true,12),o)
        assert(r.serial==0 and #m.particles.sources==0 and #m.ground.marks==0)
    end)
    test("impact strength preserves increasing response",function()
        local low,high=V.response(25),V.response(625)
        assert(high.spray>low.spray and high.stain>low.stain and high.seconds>low.seconds)
    end)
    test("a contact can cross the threshold without an earlier small wound",function()
        local r,m,o=fresh(); m:step(event(50,true,3),o); assert(r.particles==0)
        m:step(event(100,true,12),o); assert(r.particles==3)
        m:step(event(150,true,20),o); assert(r.particles==3)
    end)
    test("expired pre-bail evidence is not emitted",function()
        local r,m,o=fresh(); m:step(event(50,false,20),o)
        for i=2,7 do m:step(event(i*50,false,nil),o) end
        m:step(event(400,true,nil),o); assert(r.serial==0)
    end)
    test("a separated contact becomes a new impact episode",function()
        local r,m,o=fresh(); m:step(event(50,true,12),o)
        local hits=m.hits
        for i=2,20 do m:step(event(i*50,true,nil),o) end
        m:step(event(1050,true,12,.4),o)
        assert(m.hits==hits+1 and r.particles==6)
    end)
    test("measured rotation at a contact can produce an impact",function()
        local r,m,o=fresh()
        local function rotated(at,angle,contact)
            local e=event(at,true,contact and 0 or nil)
            local c,s=math.cos(angle),math.sin(angle)
            e.poses["Left forearm"].transform=V.matrix(vector.create(c,s,0),vector.create(-s,c,0),vector.create(0,0,1),vector.create(0,.15,0))
            if contact then e.bodies["Left forearm"].point={.7,0,0} end
            return e
        end
        m:step(rotated(50,0,false),o)
        m:step(rotated(100,-.5,false),o)
        m:step(rotated(150,-.5,true),o)
        assert(r.particles==3 and r.decals==1)
    end)
    reskate.console.print(string.format("blood: %d tests passed",passed))
end}

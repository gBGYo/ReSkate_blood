-- Appended after the plugin factories by tools/test_plugin.py.
local now, epoch, ready, teleport = 0, 1, true, false
local events, commands, storage, live, lines = {}, {}, {}, {}, {}
local serial, stopped, passed = 0, 0, 0
local menu
local function check(value, message)
    assert(value, message)
    passed += 1
end
local function effect(asset, transform, kind, options)
    assert(declared_effects[asset], "Undeclared effect: " .. asset)
    assert(#transform == 16 and transform[16] == 1)
    serial += 1
    live[serial] = {asset=asset, transform=transform, kind=kind, options=options}
    return serial
end
local api = {
    state=function() return ready, epoch end,
    clear=function() live={} end,
    particle=function(asset, transform) return effect(asset, transform, "particle") end,
    decal=function(asset, transform, options) return effect(asset, transform, "decal", options) end,
    move=function(id, transform) assert(live[id]); live[id].transform=transform end,
    stop=function(id) assert(live[id]); stopped+=1 end,
    opacity=function(id, value) assert(live[id] and value>=0 and value<=1) end,
    release=function(id) assert(live[id]); live[id]=nil end,
}
reskate = {
    effects=api,
    time={now=function() return now end},
    storage={get=function(key) return storage[key] end, set=function(key, value) storage[key]=table.clone(value) end},
    skater={telemetry=function() return {teleport_pending=teleport} end},
    on=function(name, callback)
        events[name]=events[name] or {}
        table.insert(events[name],callback)
    end,
    menu={page=function(name, callback) assert(name=="Blood"); menu=callback end},
    console={
        command=function(name, help, callback) commands[name]=callback end,
        print=function(line) table.insert(lines,line); print(line) end,
    },
}
local function emit(name, event)
    for _,callback in events[name] or {} do callback(event) end
end
local function command(...)
    commands.blood({...})
end
local function count(kind)
    local n=0
    for _,value in live do if not kind or value.kind==kind then n+=1 end end
    return n
end
local function step(bailed, speed, age)
    now+=50
    local pose={1,0,0,0,0,1,0,0,0,0,1,0,0,.15,0,1}
    local bodies={}
    if speed then bodies["Left forearm"]={impact=speed,world=true,point={0,0,0},normal={0,1,0}} end
    emit("physics_step",{at=now-(age or 0),seconds=.05,wipeout=bailed,ragdoll=bailed,bodies=bodies,
        poses={Pelvis={transform=pose,velocity={5,-10,0}},["Left forearm"]={transform=pose,velocity={5,-10,0}}}})
    emit("tick")
end
local function fall()
    step(false)
    step(true,12)
end

load_plugin()
check(menu~=nil and commands.blood~=nil,"The entry registers its menu and console command")
command("test")
check(lines[#lines]=="blood: 20 tests passed","All original model tests ran")
fall()
check(count()==0,"Effects start disabled")
command("on")
fall()
check(count("particle")==3 and count("decal")==1,"A local impact creates spray, droplets, a trail and a stain")
step(false)
check(count("decal")==1 and stopped==3,"Recovery keeps stains and stops emission")
epoch+=1; live={}; emit("tick")
check(count()==0,"A native world reset discards old handles")
fall()
check(count()==4,"A new world rearms impact detection")
command("color","3")
check(count()==0 and storage.options.color==3,"Changing pigment clears marks and saves settings")
fall()
local blue=true
for _,value in live do blue=blue and value.asset:find("_blue")~=nil end
check(blue and count()==4,"The new pigment selects declared blue assets")
ready=false; emit("tick")
check(count()==0,"Rendering suspension clears the scene")
ready=true
fall()
check(count()==4,"Rendering resumes with fresh samples")
teleport=true; step(true,12); teleport=false
check(count()==0,"A pending teleport clears effects")
fall()
now+=251; emit("tick")
check(count()==0,"A stalled physics stream clears effects")
step(false,nil,251); step(true,12,251)
check(count()==0,"Stale physics samples cannot emit effects")
fall()
emit("level_unloading")
check(count()==0,"Level unload clears effects")
fall()
emit("level_loaded")
check(count()==0,"Level load clears effects")
fall()
emit("unload")
check(count()==0,"Plugin unload clears effects")
events,commands={},{}
load_plugin()
command()
check(lines[#lines]:find("blood: on; color 3;")~=nil,"Settings survive reload")
fall()
command("off")
check(count()==0 and not storage.options.enabled,"Disabling effects clears the scene and persists")
command("on"); fall(); command("clear")
check(count()==0 and storage.options.enabled,"Clear marks preserves the enabled setting")

local ui={}
function ui:heading(_) end
function ui:label(_) end
function ui:toggle(_,_,value) return value end
function ui:slider(_,_,value,_,_) return value end
function ui:dropdown(_,_,_,value) return value end
function ui:button(id,_) return id=="reset" end
fall(); menu(ui)
check(count()==0 and not storage.options.enabled and storage.options.color==1,"The menu resets settings and clears effects")
print(string.format("blood: %d lifecycle checks passed",passed))

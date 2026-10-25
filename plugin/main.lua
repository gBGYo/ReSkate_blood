local Model=require("model")
local options=Model.options(reskate.storage.get("options"))
local model=Model.new(reskate.effects)
local epoch,ready,last_sample
local status="Blood effects are off."
local function reset() model:clear(); last_sample=nil end
local function update(value)
    local next_options=Model.options(value)
    if next_options.enabled~=options.enabled or next_options.color~=options.color or next_options.strength==0 then reset() end
    options=next_options
    reskate.storage.set("options",options)
end
local function available()
    local current,generation=reskate.effects.state()
    if generation~=epoch or (ready and not current) then reset() end
    ready,epoch=current,generation
    return current
end
reskate.on("physics_step",function(e)
    if not options.enabled or options.strength<=0 or not available() then return end
    -- Queued samples belong to their own physics time, never to a later world.
    if reskate.time.now()-e.at>250 then return end
    local telemetry=reskate.skater.telemetry()
    if telemetry and telemetry.teleport_pending then reset(); return end
    model:step(e,options); last_sample=reskate.time.now()
end)
reskate.on("tick",function()
    local active=available()
    if not options.enabled or options.strength<=0 then status="Blood effects are off."; return end
    if not active then status="Waiting for a local skater outside loading, replay, Noclip and the park editor."; return end
    if not last_sample or reskate.time.now()-last_sample>250 then
        if last_sample then reset() end
        status="Waiting for local physics samples."; return
    end
    model:render()
    status=string.format("%d impacts, %d particle sources, %d marks. Install the matching Blood assets if effects are missing.",
        model.hits,#model.particles.sources,#model.ground.marks)
end)
for _,event in {"level_unloading","level_loaded","unload"} do reskate.on(event,reset) end
reskate.menu.page("Blood",function(ui)
    ui:heading("Blood")
    ui:label("Impact spray, droplets and persistent smears for your local skater.")
    local next_options=table.clone(options)
    next_options.enabled=ui:toggle("enabled","Blood effects",options.enabled)
    next_options.reduced=ui:toggle("reduced","Reduced effects",options.reduced)
    next_options.strength=ui:slider("strength","Effect size",options.strength,0,1)
    next_options.minimum_damage=ui:slider("minimum_damage","Minimum impact damage",options.minimum_damage,0,3600)
    next_options.density=ui:slider("density","Trail density",options.density,.25,3)
    next_options.width=ui:slider("width","Smear width",options.width,.25,3)
    next_options.length=ui:slider("length","Smear length",options.length,.25,3)
    next_options.bleeding=ui:slider("bleeding","Bleeding duration",options.bleeding,.25,5)
    next_options.lifetime=ui:slider("lifetime","Mark lifetime (seconds)",options.lifetime,10,300)
    next_options.color=ui:dropdown("color","Color",{"Red","Green","Blue","Pink"},options.color)
    if ui:button("clear","Clear marks") then reset() end
    if ui:button("reset","Reset settings") then next_options=table.clone(Model.defaults) end
    for key,value in next_options do if value~=options[key] then update(next_options); break end end
    ui:label(status)
end)
reskate.console.command("blood","Blood settings and diagnostics: on, off, clear, color <1-4>, test",function(args)
    local word=args[1]
    if word=="on" or word=="off" then local o=table.clone(options); o.enabled=word=="on"; update(o)
    elseif word=="clear" then reset()
    elseif word=="color" then local o=table.clone(options); o.color=tonumber(args[2]); update(o)
    elseif word=="test" then require("tests").run(); return end
    reskate.console.print(string.format("blood: %s; color %d; %s",options.enabled and "on" or "off",options.color,status))
end)

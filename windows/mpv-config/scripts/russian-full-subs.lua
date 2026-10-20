local mp = require 'mp'

local function lower(value)
    return string.lower(value or '')
end

local function russian(track)
    local lang = lower(track.lang)
    local title = lower(track.title)
    return lang == 'ru' or lang == 'rus' or
        string.match(lang, '^ru[-_]') or string.match(lang, '^rus[-_]') or
        string.match(title, 'russian') or string.match(title, '^rus[^a-z]')
end

local function forced(track)
    local title = lower(track.title)
    local raw_title = track.title or ''
    return track.forced == true or string.match(title, 'forced') or
        string.match(title, 'signs') or string.match(title, 'songs') or
        string.find(raw_title, 'Форс', 1, true) or string.find(raw_title, 'форс', 1, true) or
        string.find(raw_title, 'Надпис', 1, true) or string.find(raw_title, 'надпис', 1, true)
end

local function score(track)
    local title = lower(track.title)
    local raw_title = track.title or ''
    local value = 10
    if string.match(title, 'full') or string.match(title, 'complete') or
        string.find(raw_title, 'Полные', 1, true) or string.find(raw_title, 'полные', 1, true) or
        string.find(raw_title, 'Полный', 1, true) or string.find(raw_title, 'полный', 1, true) then
        value = value + 100
    end
    if string.match(title, 'sdh') or string.match(title, 'hearing') then value = value - 10 end
    return value
end

local function choose_subtitle()
    local tracks = mp.get_property_native('track-list', {})
    local best = nil
    local best_score = -100000

    for _, track in ipairs(tracks) do
        if track.type == 'sub' and russian(track) and not forced(track) then
            local current = score(track)
            if current > best_score then
                best = track
                best_score = current
            end
        end
    end

    if best then
        mp.set_property('sid', tostring(best.id))
        mp.msg.info('Selected Russian non-forced subtitle track: ' .. tostring(best.id))
    else
        mp.set_property('sid', 'no')
        mp.msg.info('Russian non-forced subtitle track was not found')
    end
end

mp.register_event('file-loaded', function()
    mp.add_timeout(0.35, choose_subtitle)
end)

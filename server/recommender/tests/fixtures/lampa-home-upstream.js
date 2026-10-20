// Test fixture: yumata/lampa-source (GPL-2.0), fetched 2026-09-28.
// src/core/api/sources/cub.js main; api/api.js partNext; content_rows.js call.
function main(params = {}, oncomplite, onerror){
    let parts_limit = 6
    let parts_data  = [
        (call)=>{
            get('?sort=now_playing',params,(json)=>{
                json.title = Lang.translate('title_now_watch')

                call(json)
            },call, {life: day * 2})
        },
        (call)=>{
            get('?sort=latest',params,(json)=>{
                json.title = Lang.translate('title_latest')

                call(json)
            },call, {life: day * 2})
        },
        (call)=>{
            if(Permit.child_small) return call()

            get('top/fire/movie',params,(json)=>{
                json.title = Lang.translate('title_fire')

                json.icon_svg     = Template.string('icon_fire')
                json.icon_bgcolor = '#fff'
                json.icon_color   = '#fd4518'

                json.params = {
                    module: LineModule.toggle(LineModule.MASK.base, 'Icon')
                }

                call(json)
            },call, {life: day * 7})
        },
        (call)=>{
            get('?cat='+params.url+'&sort=latest&uhd=true',params,(json)=>{
                json.title = Lang.translate('title_in_high_quality')

                json.results.forEach(card=>{
                    card.params = {
                        style: {
                            name: 'wide',
                        }
                    }
                })

                json.params = {
                    items: {
                        view: 3
                    }
                }

                call(json)
            },call, {life: day * 3})
        },
        (call)=>{
            if(Permit.child_small) return call()

            get('top/hundred/movie',params,(json)=>{
                json.title  = Lang.translate('title_top_100') + ' - ' + Lang.translate('menu_movies')

                json.icon_svg     = Template.string('icon_top')
                json.icon_bgcolor = '#e02129'

                json.params = {
                    module: LineModule.toggle(LineModule.MASK.base, 'Icon')
                }

                call(json)
            },call, {life: day * 7})
        },
        (call)=>{
            if(Permit.child_small) return call()

            get('top/hundred/tv',params,(json)=>{
                json.title  = Lang.translate('title_top_100') + ' - ' + Lang.translate('menu_tv')

                json.icon_svg     = Template.string('icon_top')
                json.icon_bgcolor = '#e02129'

                json.params = {
                    module: LineModule.toggle(LineModule.MASK.base, 'Icon')
                }

                call(json)
            },call, {life: day * 7})
        },
        (call)=>{
            if(Permit.child) return call()

            trailers('added',call,call)
        }
    ]

    ContentRows.call('main', params, parts_data)

    let start_shuffle = parts_data.length + 1

    if(!Permit.child_small) Arrays.insert(parts_data, 0, Api.partPersons(parts_data, parts_limit, 'movie', start_shuffle))

    TMDB.genres.movie.filter(a=>!(a.id == 10763 || a.id == 10767)).forEach(genre=>{
        let event = (call)=>{
            get('?sort=top&genre='+genre.id+(Permit.child_small ? ',16' : ''),params,(json)=>{
                json.title = Lang.translate(genre.title.replace(/[^a-z_]/g,''))

                call(json)
            },call, {life: day * 7})
        }

        parts_data.push(event)
    })

    if(!Permit.child_small){
        network.silent(Utils.protocol() + Manifest.cub_domain + '/api/collections/list?category=new',(data)=>{
            data.results.forEach((collection,index)=>{
                let event = (call_inner)=>{
                    get('collections/'+collection.id,{},(json)=>{
                        json.title        = Utils.capitalizeFirstLetter(collection.title)
                        json.icon_svg     = Template.string('icon_collection')
                        json.icon_color   = '#fff'
                        json.icon_bgcolor = 'rgba(255,255,255,0.15)'

                        json.params = {
                            module: LineModule.toggle(LineModule.MASK.base, 'Icon')
                        }

                        call_inner(json)
                    },call_inner, {life: day * 3})
                }

                parts_data.push(event)
            })

            Arrays.shuffleArrayFromIndex(parts_data, start_shuffle)
        },false, false, {cache:  {life: day * 3}})
    }

    function loadPart(partLoaded, partEmpty){
        Api.partNext(parts_data, parts_limit, partLoaded, partEmpty)
    }

    loadPart(oncomplite, onerror)

    return loadPart
}

function partNext(parts, parts_limit, partLoaded, partEmpty){
    let pieces = parts.filter(p=>typeof p == 'function').slice(0,0 + parts_limit)

    if(pieces.length){
        let progress = new Progress()

        progress.append(pieces)

        progress.start((result)=>{
            let data = result.filter(r=>r && r.results && r.results.length)

            for(let i = 0; i < pieces.length; i++){
                parts[parts.indexOf(pieces[i])] = false
            }

            if(data.length){
                if(data.length < 3){
                    partNext(parts, parts_limit, (more_data)=>{
                        data = data.concat(more_data)

                        partLoaded(data)
                    }, ()=>{
                        partLoaded(data)
                    })
                }
                else partLoaded(data)
            }
            else partNext(parts, parts_limit, partLoaded, partEmpty)
        })
    }
    else partEmpty()
}

function call(screen, params, calls){
    let stop = ['genres', 'keywords']

    if(stop.find(a=>params[a])) return

    rows.filter(row=>{
        return row.screen ? (Arrays.isArray(row.screen) ? row.screen.indexOf(screen) >= 0 : row.screen == screen) : false
    }).filter(row=>{
        return Storage.get(component + '_' + (row.name || 'unknown'), 'true')
    }).forEach((row)=>{
        let result = row.call(params, screen)

        if(Arrays.isArray(result)){
            result.forEach((callback, i)=>{
                if(typeof callback == 'function'){
                    Arrays.insert(calls, (row.index || 0) + i, callback)
                }
                else if(Arrays.isObject(callback)){
                    Arrays.insert(calls, (row.index || 0) + i, callback)
                }
            })
        }
        else if(Arrays.isObject(result)){
            Arrays.insert(calls, row.index || 0, result)
        }
        else if(typeof result == 'function'){
            Arrays.insert(calls, row.index || 0, result)
        }
    })
}

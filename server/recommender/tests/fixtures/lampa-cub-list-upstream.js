// Source: yumata/lampa-source src/core/api/sources/cub.js, fetched 2026-09-30.
function url(u, params = {}){
    let genre = params.genres

    if(Permit.child_small) genre = genre ? genre + (genre == '16' ? '' : ',16') : '16'

    if(genre && u.indexOf('genre') == -1)  u = add(u, 'genre='+genre)
    if(params.page)    u = add(u, 'page='+params.page)
    if(params.query)   u = add(u, 'query='+params.query)

    if(params.filter){
        for(let i in params.filter){
            u = add(u, i+'='+params.filter[i])
        }
    }

    let email = Storage.get('account','{}').email || ''

    return Utils.addUrlComponent(Utils.protocol() + 'tmdb.'+Manifest.cub_domain+'/' + u, 'email=' + encodeURIComponent(email))
}

function add(u, params){
    return u + (/\?/.test(u) ? '&' : '?') + params;
}

function get(method, params = {}, oncomplite, onerror, cache = false){
    let u = url(method, params)

    network.silent(u,(json)=>{
        json.url = method
        json.source = source

        // Фильтруем результаты по ключевым словам, чтобы не показывать фильмы с неуместными словами в названии
        if(json.results && Arrays.isArray(json.results)){
            json.results = json.results.filter(item => {
                let title = (item.title || item.name || '').toLowerCase()

                return !Keys.filter.find(word => {
                    let reg = new RegExp(word, 'i')

                    return reg.test(title)
                })
            })
        }

        oncomplite(Utils.addSource(json, source))
    }, onerror, false, {
        cache: cache
    })
}

function list(params = {}, oncomplite, onerror){
    let u = url(params.url, params)

    network.silent(u, (data)=>{
        oncomplite(Utils.addSource(data, source))
    }, onerror, false, {
        cache: {life: day * 2}
    })
}


const publicCub = {list};

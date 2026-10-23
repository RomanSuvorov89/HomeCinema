// Upstream: yumata/lampa-source (GPL-2.0), src/components/torrents.js.
// selectedFilter fetched 2026-10-23; body retained to reproduce the actual renderer contract.
function nativeSelectedFilter(){
        let need   = this.getFilterData(),
            select = []

        for(let i in need){
            if(need[i]){
                if(Arrays.isArray(need[i])){
                    if(need[i].length) select.push(filter_translate[i] + ':' + need[i].join(', '))
                }
                else{
                    select.push(filter_translate[i] + ': ' + filter_items[i][need[i]])
                }
            }
        }

        filter.chosen('filter', select)
    }



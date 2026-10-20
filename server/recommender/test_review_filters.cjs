const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const source = fs.readFileSync('kinopoisk.js', 'utf8');
const code = source.slice(source.indexOf('  function filterReviewItems('), source.indexOf('  function openReviewList('));
const scope = {};
vm.runInNewContext(code, scope);
const items = [
 {kp_id:1,title:'Б',media_type:'movie',release_year:2001,kp_rating:8,countries:['Россия'],genres:['драма'],final_score:10},
 {kp_id:2,title:'А',media_type:'tv',release_year:2025,kp_rating:7,countries:['США'],genres:['фантастика'],feedback:'want',final_score:20},
 {kp_id:3,title:'В',media_type:'movie',release_year:2025,kp_rating:null,countries:[],genres:[],final_score:5}
];
const ids = filters => Array.from(scope.filterReviewItems(items, filters), x => x.kp_id);
assert.deepEqual(ids({}), [2,1,3]);
assert.deepEqual(ids({type:'movie',year:'2025'}), [3]);
assert.deepEqual(ids({rating:'7',country:'Россия'}), [1]);
assert.deepEqual(ids({genre:'фантастика',status:'want'}), [2]);
assert.deepEqual(ids({status:'new',sort:'year'}), [3,1]);
assert.deepEqual(ids({sort:'title'}), [2,1,3]);
assert.deepEqual(ids({rating:'9'}), []);
assert.deepEqual(items.map(x => x.kp_id), [1,2,3]);
console.log('Review filters: passed');

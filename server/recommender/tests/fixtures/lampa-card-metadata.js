// Source: installed yumata/lampa app.min.js, captured 2026-11-12.
// Installed UI reported tree 0f50f0c4cb3f602ecaff84925dca07f96bbd38a8; function names are build-local.
// Exact functions from the installed UI; captured for the metadata-card regression.

  function isObject(a) {
    return Object.prototype.toString.call(a) === '[object Object]';
  }

  function extend(a, b, replase) {
    for (var i in b) {
      if (isObject(b[i])) {
        if (a[i] == undefined) a[i] = {};
        this.extend(a[i], b[i], replase);
      } else if (a[i] == undefined || replase) a[i] = b[i];
    }
  }

  function dcma(media, id) {
    return window.lampa_settings.dcma && window.lampa_settings.dcma.find(function (a) {
      return a.cat == media && a.id == id;
    });
  }

  function Status(need) {
    this.data = {};
    this.work = 0;
    this.need = need;
    this.complited = false;

    this.check = function () {
      if (this.stopped) return;

      if (this.work >= this.need && !this.complited) {
        this.complited = true;
        this.onComplite(this.data);
      }
    };

    this.append = function (name, json) {
      this.work++;
      this.data[name] = json;
      this.check();
    };

    this.error = function () {
      this.work++;
      this.check();
    };

    this.stop = function () {
      this.stopped = true;
    };
  }

  function full$1(params, oncomplite, onerror) {
    var status = new Status(9);
    status.onComplite = oncomplite;
    if (Utils$1.dcma(params.method, params.id)) return onerror();
    var image_language = (Storage.field('tmdb_lang') || 'en').split(/[-_]/)[0];
    var image_languages = [image_language, 'en', 'null'].filter(function (language, index, list) {
      return list.indexOf(language) == index;
    }).join(',');
    get$7('3/' + params.method + '/' + params.id + '?api_key=' + TMDB$1.key() + '&append_to_response=content_ratings,release_dates,external_ids,keywords,alternative_titles,images&include_image_language=' + image_languages + '&language=' + Storage.field('tmdb_lang'), params, function (json) {
      var _json$overview;

      if (json.status_code) return status.stop(), onerror();
      json.source = 'cub';

      if (!((_json$overview = json.overview) !== null && _json$overview !== void 0 && _json$overview.trim()) && Storage.field('tmdb_lang') !== 'en') {
        TMDB.get(params.method + '/' + params.id, {
          langs: 'en'
        }, function (enjson) {
          var _enjson$overview;

          if ((_enjson$overview = enjson.overview) !== null && _enjson$overview !== void 0 && _enjson$overview.trim()) json.overview = enjson.overview;
          status.need--;
          status.check();
        }, status.error.bind(status), {
          life: day * 7
        });
      } else status.need--;

      if (params.method == 'tv') {
        var season = Utils$1.countSeasons(json);
        TMDB.get('tv/' + json.id + '/season/' + season, {}, function (ep) {
          status.append('episodes', ep);
        }, status.error.bind(status), {
          life: day * 3
        });
      } else status.need--;

      if (json.belongs_to_collection) {
        TMDB.get('collection/' + json.belongs_to_collection.id, {}, function (collection) {
          collection.results = collection.parts.slice(0, 19);
          status.append('collection', Utils$1.addSource(collection, 'tmdb'));
        }, status.error.bind(status), {
          life: day * 7
        });
      } else status.need--;

      status.append('movie', json);
    }, function () {
      status.need -= 2;
      status.error();
    }, {
      life: day * 7
    });

    if (!permit.child_small) {
      TMDB.get(params.method + '/' + params.id + '/credits', params, function (json) {
        status.append('persons', json);
      }, status.error.bind(status), {
        life: day * 7
      });
      TMDB.get(params.method + '/' + params.id + '/recommendations', params, function (json) {
        status.append('recomend', json);
      }, status.error.bind(status), {
        life: day * 7
      });
      TMDB.get(params.method + '/' + params.id + '/similar', params, function (json) {
        status.append('simular', json);
      }, status.error.bind(status), {
        life: day * 7
      });

      if (!permit.child) {
        TMDB.videos(params, function (json) {
          status.append('videos', json);
        }, status.error.bind(status));
      } else {
        status.need -= 1;
      }
    } else {
      status.need -= 4;
    }

    reactionsGet(params, function (json) {
      status.append('reactions', json);
    });

    if (Lang.selected(['ru', 'uk', 'be']) && window.lampa_settings.account_use && !permit.child) {
      status.need++;
      discussGet(params, function (json) {
        status.append('discuss', json);
      }, status.error.bind(status));
    }

    if (params.method == 'movie') {
      status.need++;
      metadataGet(params, function (json) {
        status.append('metadata', json);
      }, status.error.bind(status));
    }
  }

  function full$3() {
    var params = arguments.length > 0 && arguments[0] !== undefined ? arguments[0] : {};
    var oncomplite = arguments.length > 1 ? arguments[1] : undefined;
    var onerror = arguments.length > 2 ? arguments[2] : undefined;
    var status = new Status(9);
    status.onComplite = oncomplite;
    var image_language = (Storage.field('tmdb_lang') || 'en').split(/[-_]/)[0];
    var image_languages = [image_language, 'en', 'null'].filter(function (language, index, list) {
      return list.indexOf(language) == index;
    }).join(',');
    if (Utils$1.dcma(params.method, params.id)) return onerror();
    get$c(params.method + '/' + params.id + '?append_to_response=content_ratings,release_dates,external_ids,keywords,alternative_titles,images&include_image_language=' + image_languages, params, function (json) {
      var _json$overview;

      json.source = 'tmdb';

      if (json.external_ids) {
        json.imdb_id = json.external_ids.imdb_id;
      }

      if (!((_json$overview = json.overview) !== null && _json$overview !== void 0 && _json$overview.trim()) && Storage.field('tmdb_lang') !== 'en') {
        get$c(params.method + '/' + params.id, {
          langs: 'en'
        }, function (enjson) {
          var _enjson$overview;

          if ((_enjson$overview = enjson.overview) !== null && _enjson$overview !== void 0 && _enjson$overview.trim()) json.overview = enjson.overview;
          status.need--;
          status.check();
        }, status.error.bind(status), {
          life: day$1 * 7
        });
      } else status.need--;

      if (params.method == 'tv') {
        var season = Utils$1.countSeasons(json);
        get$c('tv/' + json.id + '/season/' + season, {}, function (ep) {
          status.append('episodes', ep);
        }, status.error.bind(status), {
          life: day$1 * 3
        });
      } else status.need--;

      if (json.belongs_to_collection) {
        get$c('collection/' + json.belongs_to_collection.id, {}, function (collection) {
          collection.results = collection.parts.slice(0, 19);
          status.append('collection', collection);
        }, status.error.bind(status), {
          life: day$1 * 7
        });
      } else status.need--;

      status.append('movie', json);
    }, function () {
      status.need -= 2;
      status.error();
    }, {
      life: day$1 * 7
    });

    if (!permit.child_small) {
      get$c(params.method + '/' + params.id + '/credits', params, function (json) {
        status.append('persons', json);
      }, status.error.bind(status), {
        life: day$1 * 7
      });
      get$c(params.method + '/' + params.id + '/recommendations', params, function (json) {
        status.append('recomend', json);
      }, status.error.bind(status), {
        life: day$1 * 7
      });
      get$c(params.method + '/' + params.id + '/similar', params, function (json) {
        status.append('simular', json);
      }, status.error.bind(status), {
        life: day$1 * 7
      });

      if (!permit.child) {
        videos(params, function (json) {
          status.append('videos', json);
        }, status.error.bind(status));
      } else {
        status.need--;
      }
    } else {
      status.need -= 4;
    }

    Api.sources.cub.reactionsGet(params, function (json) {
      status.append('reactions', json);
    });

    if (Lang.selected(['ru', 'uk', 'be']) && window.lampa_settings.account_use && !permit.child) {
      status.need++;
      Api.sources.cub.discussGet(params, function (json) {
        status.append('discuss', json);
      }, status.error.bind(status));
    }

    if (params.method == 'movie') {
      status.need++;
      Api.sources.cub.metadataGet(params, function (json) {
        status.append('metadata', json);
      }, status.error.bind(status));
    }
  }

  function init$5() {
    if (!window.lampa_settings.disable_features.dmca) {
      // Cache.getData('other', 'dcma', 60 * 24 * 10).then((result)=>{
      //     if(result && Arrays.isArray(result)) window.lampa_settings.dcma = result
      //     else{
      Lampa.Network.silent(Utils$1.protocol() + 'tmdb.' + object$2.cub_domain + '/blocked', function (dcma) {
        window.lampa_settings.dcma = dcma; //Cache.rewriteData('other', 'dcma', dcma).catch((e)=>{})
      }); //     }
      // }).catch(e=>{})
    }
  }

  function full() {
    var params = arguments.length > 0 && arguments[0] !== undefined ? arguments[0] : {};
    var oncomplite = arguments.length > 1 ? arguments[1] : undefined;
    var onerror = arguments.length > 2 ? arguments[2] : undefined;
    source(params).full(params, oncomplite, onerror);
  }

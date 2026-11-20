import{b2 as De,b1 as Se,g as Me,s as Ce,x as Ee,v as Ie,a as Ye,b as Ae,_ as l,c as lt,k as Tt,d as $e,b8 as U,l as nt,m as Fe,p as Le,C as Oe,u as We}from"../app.BfpS8Sll.js";import{t as Pe,m as Ve,a as ze,l as Re,h as Ne,c as Qt,d as Kt,e as He,g as Be,i as Ge,j as je,k as Ue,n as Xe,p as qe,q as Jt,r as te,s as ee,u as re,v as ne}from"./d3-scale.DlYbYB9H.js";import"./framework.DmEmLUcc.js";import"./theme.BQkihYpY.js";function Ze(t){return t}var bt=1,It=2,Ft=3,xt=4,se=1e-6;function Qe(t){return"translate("+t+",0)"}function Ke(t){return"translate(0,"+t+")"}function Je(t){return e=>+t(e)}function tr(t,e){return e=Math.max(0,t.bandwidth()-e*2)/2,t.round()&&(e=Math.round(e)),r=>+t(r)+e}function er(){return!this.__axis}function de(t,e){var r=[],n=null,s=null,o=6,d=6,x=3,v=typeof window<"u"&&window.devicePixelRatio>1?0:.5,M=t===bt||t===xt?-1:1,D=t===xt||t===It?"x":"y",L=t===bt||t===Ft?Qe:Ke;function _(w){var W=n??(e.ticks?e.ticks.apply(e,r):e.domain()),O=s??(e.tickFormat?e.tickFormat.apply(e,r):Ze),S=Math.max(o,0)+x,z=e.range(),X=+z[0]+v,R=+z[z.length-1]+v,G=(e.bandwidth?tr:Je)(e.copy(),v),H=w.selection?w.selection():w,C=H.selectAll(".domain").data([null]),g=H.selectAll(".tick").data(W,e).order(),m=g.exit(),F=g.enter().append("g").attr("class","tick"),k=g.select("line"),b=g.select("text");C=C.merge(C.enter().insert("path",".tick").attr("class","domain").attr("stroke","currentColor")),g=g.merge(F),k=k.merge(F.append("line").attr("stroke","currentColor").attr(D+"2",M*o)),b=b.merge(F.append("text").attr("fill","currentColor").attr(D,M*S).attr("dy",t===bt?"0em":t===Ft?"0.71em":"0.32em")),w!==H&&(C=C.transition(w),g=g.transition(w),k=k.transition(w),b=b.transition(w),m=m.transition(w).attr("opacity",se).attr("transform",function(p){return isFinite(p=G(p))?L(p+v):this.getAttribute("transform")}),F.attr("opacity",se).attr("transform",function(p){var T=this.parentNode.__axis;return L((T&&isFinite(T=T(p))?T:G(p))+v)})),m.remove(),C.attr("d",t===xt||t===It?d?"M"+M*d+","+X+"H"+v+"V"+R+"H"+M*d:"M"+v+","+X+"V"+R:d?"M"+X+","+M*d+"V"+v+"H"+R+"V"+M*d:"M"+X+","+v+"H"+R),g.attr("opacity",1).attr("transform",function(p){return L(G(p)+v)}),k.attr(D+"2",M*o),b.attr(D,M*S).text(O),H.filter(er).attr("fill","none").attr("font-size",10).attr("font-family","sans-serif").attr("text-anchor",t===It?"start":t===xt?"end":"middle"),H.each(function(){this.__axis=G})}return _.scale=function(w){return arguments.length?(e=w,_):e},_.ticks=function(){return r=Array.from(arguments),_},_.tickArguments=function(w){return arguments.length?(r=w==null?[]:Array.from(w),_):r.slice()},_.tickValues=function(w){return arguments.length?(n=w==null?null:Array.from(w),_):n&&n.slice()},_.tickFormat=function(w){return arguments.length?(s=w,_):s},_.tickSize=function(w){return arguments.length?(o=d=+w,_):o},_.tickSizeInner=function(w){return arguments.length?(o=+w,_):o},_.tickSizeOuter=function(w){return arguments.length?(d=+w,_):d},_.tickPadding=function(w){return arguments.length?(x=+w,_):x},_.offset=function(w){return arguments.length?(v=+w,_):v},_}function rr(t){return de(bt,t)}function nr(t){return de(Ft,t)}var Yt="day",sr="week",ir="year",ar="YYYY-MM-DDTHH:mm:ssZ",or="isoweek";const cr=function(t,e,r){var n=function(v,M){var D=(M?r.utc:r)().year(v).startOf(ir),L=4-D.isoWeekday();return D.isoWeekday()>4&&(L+=7),D.add(L,Yt)},s=function(v){return v.add(4-v.isoWeekday(),Yt)},o=e.prototype;o.isoWeekYear=function(){var x=s(this);return x.year()},o.isoWeek=function(x){if(!this.$utils().u(x))return this.add((x-this.isoWeek())*7,Yt);var v=s(this),M=n(this.isoWeekYear(),this.$u);return v.diff(M,sr)+1},o.isoWeekday=function(x){return this.$utils().u(x)?this.day()||7:this.day(this.day()%7?x:x-7)};var d=o.startOf;o.startOf=function(x,v){var M=this.$utils(),D=M.u(v)?!0:v,L=M.p(x);return L===or?D?this.date(this.date()-(this.isoWeekday()-1)).startOf("day"):this.date(this.date()-1-(this.isoWeekday()-1)+7).endOf("day"):d.bind(this)(x,v)}};var lr=function(e){return e.replace(/(\[[^\]]+])|(MMMM|MM|DD|dddd)/g,function(r,n,s){return n||s.slice(1)})},ur={LTS:"h:mm:ss A",LT:"h:mm A",L:"MM/DD/YYYY",LL:"MMMM D, YYYY",LLL:"MMMM D, YYYY h:mm A",LLLL:"dddd, MMMM D, YYYY h:mm A"},dr=function(e,r){return e.replace(/(\[[^\]]+])|(LTS?|l{1,4}|L{1,4})/g,function(n,s,o){var d=o&&o.toUpperCase();return s||r[o]||ur[o]||lr(r[d])})},fr=/(\[[^[]*\])|([-_:/.,()\s]+)|(A|a|Q|YYYY|YY?|ww?|MM?M?M?|Do|DD?|hh?|HH?|mm?|ss?|S{1,3}|z|ZZ?)/g,ie=/\d/,kt=/\d\d/,hr=/\d{3}/,mr=/\d{4}/,J=/\d\d?/,kr=/[+-]?\d+/,yr=/[+-]\d\d:?(\d\d)?|Z/,yt=/\d*[^-_:/,()\s\d]+/,st={},fe=function(e){return e=+e,e+(e>68?1900:2e3)};function gr(t){if(!t||t==="Z")return 0;var e=t.match(/([+-]|\d\d)/g),r=+(e[1]*60)+(+e[2]||0);return r===0?0:e[0]==="+"?-r:r}var q=function(e){return function(r){this[e]=+r}},ae=[yr,function(t){var e=this.zone||(this.zone={});e.offset=gr(t)}],At=function(e){var r=st[e];return r&&(r.indexOf?r:r.s.concat(r.f))},oe=function(e,r){var n,s=st,o=s.meridiem;if(!o)n=e===(r?"pm":"PM");else for(var d=1;d<=24;d+=1)if(e.indexOf(o(d,0,r))>-1){n=d>12;break}return n},vr={A:[yt,function(t){this.afternoon=oe(t,!1)}],a:[yt,function(t){this.afternoon=oe(t,!0)}],Q:[ie,function(t){this.month=(t-1)*3+1}],S:[ie,function(t){this.milliseconds=+t*100}],SS:[kt,function(t){this.milliseconds=+t*10}],SSS:[hr,function(t){this.milliseconds=+t}],s:[J,q("seconds")],ss:[J,q("seconds")],m:[J,q("minutes")],mm:[J,q("minutes")],H:[J,q("hours")],h:[J,q("hours")],HH:[J,q("hours")],hh:[J,q("hours")],D:[J,q("day")],DD:[kt,q("day")],Do:[yt,function(t){var e=st,r=e.ordinal,n=t.match(/\d+/);if(this.day=n[0],!!r)for(var s=1;s<=31;s+=1)r(s).replace(/\[|\]/g,"")===t&&(this.day=s)}],w:[J,q("week")],ww:[kt,q("week")],M:[J,q("month")],MM:[kt,q("month")],MMM:[yt,function(t){var e=At("months"),r=At("monthsShort"),n=(r||e.map(function(s){return s.slice(0,3)})).indexOf(t)+1;if(n<1)throw new Error;this.month=n%12||n}],MMMM:[yt,function(t){var e=At("months"),r=e.indexOf(t)+1;if(r<1)throw new Error;this.month=r%12||r}],Y:[kr,q("year")],YY:[kt,function(t){this.year=fe(t)}],YYYY:[mr,q("year")],Z:ae,ZZ:ae};function pr(t){var e=t.afternoon;if(e!==void 0){var r=t.hours;e?r<12&&(t.hours+=12):r===12&&(t.hours=0),delete t.afternoon}}function Tr(t){t=dr(t,st&&st.formats);for(var e=t.match(fr),r=e.length,n=0;n<r;n+=1){var s=e[n],o=vr[s],d=o&&o[0],x=o&&o[1];x?e[n]={regex:d,parser:x}:e[n]=s.replace(/^\[|\]$/g,"")}return function(v){for(var M={},D=0,L=0;D<r;D+=1){var _=e[D];if(typeof _=="string")L+=_.length;else{var w=_.regex,W=_.parser,O=v.slice(L),S=w.exec(O),z=S[0];W.call(M,z),v=v.replace(z,"")}}return pr(M),M}}var xr=function(e,r,n,s){try{if(["x","X"].indexOf(r)>-1)return new Date((r==="X"?1e3:1)*e);var o=Tr(r),d=o(e),x=d.year,v=d.month,M=d.day,D=d.hours,L=d.minutes,_=d.seconds,w=d.milliseconds,W=d.zone,O=d.week,S=new Date,z=M||(!x&&!v?S.getDate():1),X=x||S.getFullYear(),R=0;x&&!v||(R=v>0?v-1:S.getMonth());var G=D||0,H=L||0,C=_||0,g=w||0;if(W)return new Date(Date.UTC(X,R,z,G,H,C,g+W.offset*60*1e3));if(n)return new Date(Date.UTC(X,R,z,G,H,C,g));var m;return m=new Date(X,R,z,G,H,C,g),O&&(m=s(m).week(O).toDate()),m}catch{return new Date("")}};const br=function(t,e,r){r.p.customParseFormat=!0,t&&t.parseTwoDigitYear&&(fe=t.parseTwoDigitYear);var n=e.prototype,s=n.parse;n.parse=function(o){var d=o.date,x=o.utc,v=o.args;this.$u=x;var M=v[1];if(typeof M=="string"){var D=v[2]===!0,L=v[3]===!0,_=D||L,w=v[2];L&&(w=v[2]),st=this.$locale(),!D&&w&&(st=r.Ls[w]),this.$d=xr(d,M,x,r),this.init(),w&&w!==!0&&(this.$L=this.locale(w).$L),_&&d!=this.format(M)&&(this.$d=new Date("")),st={}}else if(M instanceof Array)for(var W=M.length,O=1;O<=W;O+=1){v[1]=M[O-1];var S=r.apply(this,v);if(S.isValid()){this.$d=S.$d,this.$L=S.$L,this.init();break}O===W&&(this.$d=new Date(""))}else s.call(this,o)}},wr=function(t,e){var r=e.prototype,n=r.format;r.format=function(s){var o=this,d=this.$locale();if(!this.isValid())return n.bind(this)(s);var x=this.$utils(),v=s||ar,M=v.replace(/\[([^\]]+)]|Q|wo|ww|w|WW|W|zzz|z|gggg|GGGG|Do|X|x|k{1,2}|S/g,function(D){switch(D){case"Q":return Math.ceil((o.$M+1)/3);case"Do":return d.ordinal(o.$D);case"gggg":return o.weekYear();case"GGGG":return o.isoWeekYear();case"wo":return d.ordinal(o.week(),"W");case"w":case"ww":return x.s(o.week(),D==="w"?1:2,"0");case"W":case"WW":return x.s(o.isoWeek(),D==="W"?1:2,"0");case"k":case"kk":return x.s(String(o.$H===0?24:o.$H),D==="k"?1:2,"0");case"X":return Math.floor(o.$d.getTime()/1e3);case"x":return o.$d.getTime();case"z":return"["+o.offsetName()+"]";case"zzz":return"["+o.offsetName("long")+"]";default:return D}});return n.bind(this)(M)}};var he={exports:{}};(function(t,e){(function(r,n){t.exports=n()})(De,function(){var r,n,s=1e3,o=6e4,d=36e5,x=864e5,v=31536e6,M=2628e6,D=/^(-|\+)?P(?:([-+]?[0-9,.]*)Y)?(?:([-+]?[0-9,.]*)M)?(?:([-+]?[0-9,.]*)W)?(?:([-+]?[0-9,.]*)D)?(?:T(?:([-+]?[0-9,.]*)H)?(?:([-+]?[0-9,.]*)M)?(?:([-+]?[0-9,.]*)S)?)?$/,L=/\[([^\]]+)]|YYYY|YY|Y|M{1,2}|D{1,2}|H{1,2}|m{1,2}|s{1,2}|SSS/g,_={years:v,months:M,days:x,hours:d,minutes:o,seconds:s,milliseconds:1,weeks:6048e5},w=function(C){return C instanceof G},W=function(C,g,m){return new G(C,m,g.$l)},O=function(C){return n.p(C)+"s"},S=function(C){return C<0},z=function(C){return S(C)?Math.ceil(C):Math.floor(C)},X=function(C){return Math.abs(C)},R=function(C,g){return C?S(C)?{negative:!0,format:""+X(C)+g}:{negative:!1,format:""+C+g}:{negative:!1,format:""}},G=function(){function C(m,F,k){var b=this;if(this.$d={},this.$l=k,m===void 0&&(this.$ms=0,this.parseFromMilliseconds()),F)return W(m*_[O(F)],this);if(typeof m=="number")return this.$ms=m,this.parseFromMilliseconds(),this;if(typeof m=="object")return Object.keys(m).forEach(function(a){b.$d[O(a)]=m[a]}),this.calMilliseconds(),this;if(typeof m=="string"){var p=m.match(D);if(p){var T=p.slice(2).map(function(a){return a!=null?Number(a):0});return this.$d.years=T[0],this.$d.months=T[1],this.$d.weeks=T[2],this.$d.days=T[3],this.$d.hours=T[4],this.$d.minutes=T[5],this.$d.seconds=T[6],this.calMilliseconds(),this}}return this}var g=C.prototype;return g.calMilliseconds=function(){var m=this;this.$ms=Object.keys(this.$d).reduce(function(F,k){return F+(m.$d[k]||0)*_[k]},0)},g.parseFromMilliseconds=function(){var m=this.$ms;this.$d.years=z(m/v),m%=v,this.$d.months=z(m/M),m%=M,this.$d.days=z(m/x),m%=x,this.$d.hours=z(m/d),m%=d,this.$d.minutes=z(m/o),m%=o,this.$d.seconds=z(m/s),m%=s,this.$d.milliseconds=m},g.toISOString=function(){var m=R(this.$d.years,"Y"),F=R(this.$d.months,"M"),k=+this.$d.days||0;this.$d.weeks&&(k+=7*this.$d.weeks);var b=R(k,"D"),p=R(this.$d.hours,"H"),T=R(this.$d.minutes,"M"),a=this.$d.seconds||0;this.$d.milliseconds&&(a+=this.$d.milliseconds/1e3,a=Math.round(1e3*a)/1e3);var h=R(a,"S"),y=m.negative||F.negative||b.negative||p.negative||T.negative||h.negative,f=p.format||T.format||h.format?"T":"",A=(y?"-":"")+"P"+m.format+F.format+b.format+f+p.format+T.format+h.format;return A==="P"||A==="-P"?"P0D":A},g.toJSON=function(){return this.toISOString()},g.format=function(m){var F=m||"YYYY-MM-DDTHH:mm:ss",k={Y:this.$d.years,YY:n.s(this.$d.years,2,"0"),YYYY:n.s(this.$d.years,4,"0"),M:this.$d.months,MM:n.s(this.$d.months,2,"0"),D:this.$d.days,DD:n.s(this.$d.days,2,"0"),H:this.$d.hours,HH:n.s(this.$d.hours,2,"0"),m:this.$d.minutes,mm:n.s(this.$d.minutes,2,"0"),s:this.$d.seconds,ss:n.s(this.$d.seconds,2,"0"),SSS:n.s(this.$d.milliseconds,3,"0")};return F.replace(L,function(b,p){return p||String(k[b])})},g.as=function(m){return this.$ms/_[O(m)]},g.get=function(m){var F=this.$ms,k=O(m);return k==="milliseconds"?F%=1e3:F=k==="weeks"?z(F/_[k]):this.$d[k],F||0},g.add=function(m,F,k){var b;return b=F?m*_[O(F)]:w(m)?m.$ms:W(m,this).$ms,W(this.$ms+b*(k?-1:1),this)},g.subtract=function(m,F){return this.add(m,F,!0)},g.locale=function(m){var F=this.clone();return F.$l=m,F},g.clone=function(){return W(this.$ms,this)},g.humanize=function(m){return r().add(this.$ms,"ms").locale(this.$l).fromNow(!m)},g.valueOf=function(){return this.asMilliseconds()},g.milliseconds=function(){return this.get("milliseconds")},g.asMilliseconds=function(){return this.as("milliseconds")},g.seconds=function(){return this.get("seconds")},g.asSeconds=function(){return this.as("seconds")},g.minutes=function(){return this.get("minutes")},g.asMinutes=function(){return this.as("minutes")},g.hours=function(){return this.get("hours")},g.asHours=function(){return this.as("hours")},g.days=function(){return this.get("days")},g.asDays=function(){return this.as("days")},g.weeks=function(){return this.get("weeks")},g.asWeeks=function(){return this.as("weeks")},g.months=function(){return this.get("months")},g.asMonths=function(){return this.as("months")},g.years=function(){return this.get("years")},g.asYears=function(){return this.as("years")},C}(),H=function(C,g,m){return C.add(g.years()*m,"y").add(g.months()*m,"M").add(g.days()*m,"d").add(g.hours()*m,"h").add(g.minutes()*m,"m").add(g.seconds()*m,"s").add(g.milliseconds()*m,"ms")};return function(C,g,m){r=m,n=m().$utils(),m.duration=function(b,p){var T=m.locale();return W(b,{$l:T},p)},m.isDuration=w;var F=g.prototype.add,k=g.prototype.subtract;g.prototype.add=function(b,p){return w(b)?H(this,b,1):F.bind(this)(b,p)},g.prototype.subtract=function(b,p){return w(b)?H(this,b,-1):k.bind(this)(b,p)}}})})(he);var _r=he.exports;const Dr=Se(_r);var Lt=function(){var t=l(function(T,a,h,y){for(h=h||{},y=T.length;y--;h[T[y]]=a);return h},"o"),e=[6,8,10,12,13,14,15,16,17,18,20,21,22,23,24,25,26,27,28,29,30,31,33,35,36,38,40],r=[1,26],n=[1,27],s=[1,28],o=[1,29],d=[1,30],x=[1,31],v=[1,32],M=[1,33],D=[1,34],L=[1,9],_=[1,10],w=[1,11],W=[1,12],O=[1,13],S=[1,14],z=[1,15],X=[1,16],R=[1,19],G=[1,20],H=[1,21],C=[1,22],g=[1,23],m=[1,25],F=[1,35],k={trace:l(function(){},"trace"),yy:{},symbols_:{error:2,start:3,gantt:4,document:5,EOF:6,line:7,SPACE:8,statement:9,NL:10,weekday:11,weekday_monday:12,weekday_tuesday:13,weekday_wednesday:14,weekday_thursday:15,weekday_friday:16,weekday_saturday:17,weekday_sunday:18,weekend:19,weekend_friday:20,weekend_saturday:21,dateFormat:22,inclusiveEndDates:23,topAxis:24,axisFormat:25,tickInterval:26,excludes:27,includes:28,todayMarker:29,title:30,acc_title:31,acc_title_value:32,acc_descr:33,acc_descr_value:34,acc_descr_multiline_value:35,section:36,clickStatement:37,taskTxt:38,taskData:39,click:40,callbackname:41,callbackargs:42,href:43,clickStatementDebug:44,$accept:0,$end:1},terminals_:{2:"error",4:"gantt",6:"EOF",8:"SPACE",10:"NL",12:"weekday_monday",13:"weekday_tuesday",14:"weekday_wednesday",15:"weekday_thursday",16:"weekday_friday",17:"weekday_saturday",18:"weekday_sunday",20:"weekend_friday",21:"weekend_saturday",22:"dateFormat",23:"inclusiveEndDates",24:"topAxis",25:"axisFormat",26:"tickInterval",27:"excludes",28:"includes",29:"todayMarker",30:"title",31:"acc_title",32:"acc_title_value",33:"acc_descr",34:"acc_descr_value",35:"acc_descr_multiline_value",36:"section",38:"taskTxt",39:"taskData",40:"click",41:"callbackname",42:"callbackargs",43:"href"},productions_:[0,[3,3],[5,0],[5,2],[7,2],[7,1],[7,1],[7,1],[11,1],[11,1],[11,1],[11,1],[11,1],[11,1],[11,1],[19,1],[19,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,1],[9,2],[9,2],[9,1],[9,1],[9,1],[9,2],[37,2],[37,3],[37,3],[37,4],[37,3],[37,4],[37,2],[44,2],[44,3],[44,3],[44,4],[44,3],[44,4],[44,2]],performAction:l(function(a,h,y,f,A,i,$){var u=i.length-1;switch(A){case 1:return i[u-1];case 2:this.$=[];break;case 3:i[u-1].push(i[u]),this.$=i[u-1];break;case 4:case 5:this.$=i[u];break;case 6:case 7:this.$=[];break;case 8:f.setWeekday("monday");break;case 9:f.setWeekday("tuesday");break;case 10:f.setWeekday("wednesday");break;case 11:f.setWeekday("thursday");break;case 12:f.setWeekday("friday");break;case 13:f.setWeekday("saturday");break;case 14:f.setWeekday("sunday");break;case 15:f.setWeekend("friday");break;case 16:f.setWeekend("saturday");break;case 17:f.setDateFormat(i[u].substr(11)),this.$=i[u].substr(11);break;case 18:f.enableInclusiveEndDates(),this.$=i[u].substr(18);break;case 19:f.TopAxis(),this.$=i[u].substr(8);break;case 20:f.setAxisFormat(i[u].substr(11)),this.$=i[u].substr(11);break;case 21:f.setTickInterval(i[u].substr(13)),this.$=i[u].substr(13);break;case 22:f.setExcludes(i[u].substr(9)),this.$=i[u].substr(9);break;case 23:f.setIncludes(i[u].substr(9)),this.$=i[u].substr(9);break;case 24:f.setTodayMarker(i[u].substr(12)),this.$=i[u].substr(12);break;case 27:f.setDiagramTitle(i[u].substr(6)),this.$=i[u].substr(6);break;case 28:this.$=i[u].trim(),f.setAccTitle(this.$);break;case 29:case 30:this.$=i[u].trim(),f.setAccDescription(this.$);break;case 31:f.addSection(i[u].substr(8)),this.$=i[u].substr(8);break;case 33:f.addTask(i[u-1],i[u]),this.$="task";break;case 34:this.$=i[u-1],f.setClickEvent(i[u-1],i[u],null);break;case 35:this.$=i[u-2],f.setClickEvent(i[u-2],i[u-1],i[u]);break;case 36:this.$=i[u-2],f.setClickEvent(i[u-2],i[u-1],null),f.setLink(i[u-2],i[u]);break;case 37:this.$=i[u-3],f.setClickEvent(i[u-3],i[u-2],i[u-1]),f.setLink(i[u-3],i[u]);break;case 38:this.$=i[u-2],f.setClickEvent(i[u-2],i[u],null),f.setLink(i[u-2],i[u-1]);break;case 39:this.$=i[u-3],f.setClickEvent(i[u-3],i[u-1],i[u]),f.setLink(i[u-3],i[u-2]);break;case 40:this.$=i[u-1],f.setLink(i[u-1],i[u]);break;case 41:case 47:this.$=i[u-1]+" "+i[u];break;case 42:case 43:case 45:this.$=i[u-2]+" "+i[u-1]+" "+i[u];break;case 44:case 46:this.$=i[u-3]+" "+i[u-2]+" "+i[u-1]+" "+i[u];break}},"anonymous"),table:[{3:1,4:[1,2]},{1:[3]},t(e,[2,2],{5:3}),{6:[1,4],7:5,8:[1,6],9:7,10:[1,8],11:17,12:r,13:n,14:s,15:o,16:d,17:x,18:v,19:18,20:M,21:D,22:L,23:_,24:w,25:W,26:O,27:S,28:z,29:X,30:R,31:G,33:H,35:C,36:g,37:24,38:m,40:F},t(e,[2,7],{1:[2,1]}),t(e,[2,3]),{9:36,11:17,12:r,13:n,14:s,15:o,16:d,17:x,18:v,19:18,20:M,21:D,22:L,23:_,24:w,25:W,26:O,27:S,28:z,29:X,30:R,31:G,33:H,35:C,36:g,37:24,38:m,40:F},t(e,[2,5]),t(e,[2,6]),t(e,[2,17]),t(e,[2,18]),t(e,[2,19]),t(e,[2,20]),t(e,[2,21]),t(e,[2,22]),t(e,[2,23]),t(e,[2,24]),t(e,[2,25]),t(e,[2,26]),t(e,[2,27]),{32:[1,37]},{34:[1,38]},t(e,[2,30]),t(e,[2,31]),t(e,[2,32]),{39:[1,39]},t(e,[2,8]),t(e,[2,9]),t(e,[2,10]),t(e,[2,11]),t(e,[2,12]),t(e,[2,13]),t(e,[2,14]),t(e,[2,15]),t(e,[2,16]),{41:[1,40],43:[1,41]},t(e,[2,4]),t(e,[2,28]),t(e,[2,29]),t(e,[2,33]),t(e,[2,34],{42:[1,42],43:[1,43]}),t(e,[2,40],{41:[1,44]}),t(e,[2,35],{43:[1,45]}),t(e,[2,36]),t(e,[2,38],{42:[1,46]}),t(e,[2,37]),t(e,[2,39])],defaultActions:{},parseError:l(function(a,h){if(h.recoverable)this.trace(a);else{var y=new Error(a);throw y.hash=h,y}},"parseError"),parse:l(function(a){var h=this,y=[0],f=[],A=[null],i=[],$=this.table,u="",j=0,c=0,E=2,I=1,P=i.slice.call(arguments,1),Y=Object.create(this.lexer),N={yy:{}};for(var V in this.yy)Object.prototype.hasOwnProperty.call(this.yy,V)&&(N.yy[V]=this.yy[V]);Y.setInput(a,N.yy),N.yy.lexer=Y,N.yy.parser=this,typeof Y.yylloc>"u"&&(Y.yylloc={});var mt=Y.yylloc;i.push(mt);var Mt=Y.options&&Y.options.ranges;typeof N.yy.parseError=="function"?this.parseError=N.yy.parseError:this.parseError=Object.getPrototypeOf(this).parseError;function _e(Q){y.length=y.length-2*Q,A.length=A.length-Q,i.length=i.length-Q}l(_e,"popStack");function qt(){var Q;return Q=f.pop()||Y.lex()||I,typeof Q!="number"&&(Q instanceof Array&&(f=Q,Q=f.pop()),Q=h.symbols_[Q]||Q),Q}l(qt,"lex");for(var Z,it,K,Ct,ot={},vt,et,Zt,pt;;){if(it=y[y.length-1],this.defaultActions[it]?K=this.defaultActions[it]:((Z===null||typeof Z>"u")&&(Z=qt()),K=$[it]&&$[it][Z]),typeof K>"u"||!K.length||!K[0]){var Et="";pt=[];for(vt in $[it])this.terminals_[vt]&&vt>E&&pt.push("'"+this.terminals_[vt]+"'");Y.showPosition?Et="Parse error on line "+(j+1)+`:
`+Y.showPosition()+`
Expecting `+pt.join(", ")+", got '"+(this.terminals_[Z]||Z)+"'":Et="Parse error on line "+(j+1)+": Unexpected "+(Z==I?"end of input":"'"+(this.terminals_[Z]||Z)+"'"),this.parseError(Et,{text:Y.match,token:this.terminals_[Z]||Z,line:Y.yylineno,loc:mt,expected:pt})}if(K[0]instanceof Array&&K.length>1)throw new Error("Parse Error: multiple actions possible at state: "+it+", token: "+Z);switch(K[0]){case 1:y.push(Z),A.push(Y.yytext),i.push(Y.yylloc),y.push(K[1]),Z=null,c=Y.yyleng,u=Y.yytext,j=Y.yylineno,mt=Y.yylloc;break;case 2:if(et=this.productions_[K[1]][1],ot.$=A[A.length-et],ot._$={first_line:i[i.length-(et||1)].first_line,last_line:i[i.length-1].last_line,first_column:i[i.length-(et||1)].first_column,last_column:i[i.length-1].last_column},Mt&&(ot._$.range=[i[i.length-(et||1)].range[0],i[i.length-1].range[1]]),Ct=this.performAction.apply(ot,[u,c,j,N.yy,K[1],A,i].concat(P)),typeof Ct<"u")return Ct;et&&(y=y.slice(0,-1*et*2),A=A.slice(0,-1*et),i=i.slice(0,-1*et)),y.push(this.productions_[K[1]][0]),A.push(ot.$),i.push(ot._$),Zt=$[y[y.length-2]][y[y.length-1]],y.push(Zt);break;case 3:return!0}}return!0},"parse")},b=function(){var T={EOF:1,parseError:l(function(h,y){if(this.yy.parser)this.yy.parser.parseError(h,y);else throw new Error(h)},"parseError"),setInput:l(function(a,h){return this.yy=h||this.yy||{},this._input=a,this._more=this._backtrack=this.done=!1,this.yylineno=this.yyleng=0,this.yytext=this.matched=this.match="",this.conditionStack=["INITIAL"],this.yylloc={first_line:1,first_column:0,last_line:1,last_column:0},this.options.ranges&&(this.yylloc.range=[0,0]),this.offset=0,this},"setInput"),input:l(function(){var a=this._input[0];this.yytext+=a,this.yyleng++,this.offset++,this.match+=a,this.matched+=a;var h=a.match(/(?:\r\n?|\n).*/g);return h?(this.yylineno++,this.yylloc.last_line++):this.yylloc.last_column++,this.options.ranges&&this.yylloc.range[1]++,this._input=this._input.slice(1),a},"input"),unput:l(function(a){var h=a.length,y=a.split(/(?:\r\n?|\n)/g);this._input=a+this._input,this.yytext=this.yytext.substr(0,this.yytext.length-h),this.offset-=h;var f=this.match.split(/(?:\r\n?|\n)/g);this.match=this.match.substr(0,this.match.length-1),this.matched=this.matched.substr(0,this.matched.length-1),y.length-1&&(this.yylineno-=y.length-1);var A=this.yylloc.range;return this.yylloc={first_line:this.yylloc.first_line,last_line:this.yylineno+1,first_column:this.yylloc.first_column,last_column:y?(y.length===f.length?this.yylloc.first_column:0)+f[f.length-y.length].length-y[0].length:this.yylloc.first_column-h},this.options.ranges&&(this.yylloc.range=[A[0],A[0]+this.yyleng-h]),this.yyleng=this.yytext.length,this},"unput"),more:l(function(){return this._more=!0,this},"more"),reject:l(function(){if(this.options.backtrack_lexer)this._backtrack=!0;else return this.parseError("Lexical error on line "+(this.yylineno+1)+`. You can only invoke reject() in the lexer when the lexer is of the backtracking persuasion (options.backtrack_lexer = true).
`+this.showPosition(),{text:"",token:null,line:this.yylineno});return this},"reject"),less:l(function(a){this.unput(this.match.slice(a))},"less"),pastInput:l(function(){var a=this.matched.substr(0,this.matched.length-this.match.length);return(a.length>20?"...":"")+a.substr(-20).replace(/\n/g,"")},"pastInput"),upcomingInput:l(function(){var a=this.match;return a.length<20&&(a+=this._input.substr(0,20-a.length)),(a.substr(0,20)+(a.length>20?"...":"")).replace(/\n/g,"")},"upcomingInput"),showPosition:l(function(){var a=this.pastInput(),h=new Array(a.length+1).join("-");return a+this.upcomingInput()+`
`+h+"^"},"showPosition"),test_match:l(function(a,h){var y,f,A;if(this.options.backtrack_lexer&&(A={yylineno:this.yylineno,yylloc:{first_line:this.yylloc.first_line,last_line:this.last_line,first_column:this.yylloc.first_column,last_column:this.yylloc.last_column},yytext:this.yytext,match:this.match,matches:this.matches,matched:this.matched,yyleng:this.yyleng,offset:this.offset,_more:this._more,_input:this._input,yy:this.yy,conditionStack:this.conditionStack.slice(0),done:this.done},this.options.ranges&&(A.yylloc.range=this.yylloc.range.slice(0))),f=a[0].match(/(?:\r\n?|\n).*/g),f&&(this.yylineno+=f.length),this.yylloc={first_line:this.yylloc.last_line,last_line:this.yylineno+1,first_column:this.yylloc.last_column,last_column:f?f[f.length-1].length-f[f.length-1].match(/\r?\n?/)[0].length:this.yylloc.last_column+a[0].length},this.yytext+=a[0],this.match+=a[0],this.matches=a,this.yyleng=this.yytext.length,this.options.ranges&&(this.yylloc.range=[this.offset,this.offset+=this.yyleng]),this._more=!1,this._backtrack=!1,this._input=this._input.slice(a[0].length),this.matched+=a[0],y=this.performAction.call(this,this.yy,this,h,this.conditionStack[this.conditionStack.length-1]),this.done&&this._input&&(this.done=!1),y)return y;if(this._backtrack){for(var i in A)this[i]=A[i];return!1}return!1},"test_match"),next:l(function(){if(this.done)return this.EOF;this._input||(this.done=!0);var a,h,y,f;this._more||(this.yytext="",this.match="");for(var A=this._currentRules(),i=0;i<A.length;i++)if(y=this._input.match(this.rules[A[i]]),y&&(!h||y[0].length>h[0].length)){if(h=y,f=i,this.options.backtrack_lexer){if(a=this.test_match(y,A[i]),a!==!1)return a;if(this._backtrack){h=!1;continue}else return!1}else if(!this.options.flex)break}return h?(a=this.test_match(h,A[f]),a!==!1?a:!1):this._input===""?this.EOF:this.parseError("Lexical error on line "+(this.yylineno+1)+`. Unrecognized text.
`+this.showPosition(),{text:"",token:null,line:this.yylineno})},"next"),lex:l(function(){var h=this.next();return h||this.lex()},"lex"),begin:l(function(h){this.conditionStack.push(h)},"begin"),popState:l(function(){var h=this.conditionStack.length-1;return h>0?this.conditionStack.pop():this.conditionStack[0]},"popState"),_currentRules:l(function(){return this.conditionStack.length&&this.conditionStack[this.conditionStack.length-1]?this.conditions[this.conditionStack[this.conditionStack.length-1]].rules:this.conditions.INITIAL.rules},"_currentRules"),topState:l(function(h){return h=this.conditionStack.length-1-Math.abs(h||0),h>=0?this.conditionStack[h]:"INITIAL"},"topState"),pushState:l(function(h){this.begin(h)},"pushState"),stateStackSize:l(function(){return this.conditionStack.length},"stateStackSize"),options:{"case-insensitive":!0},performAction:l(function(h,y,f,A){switch(f){case 0:return this.begin("open_directive"),"open_directive";case 1:return this.begin("acc_title"),31;case 2:return this.popState(),"acc_title_value";case 3:return this.begin("acc_descr"),33;case 4:return this.popState(),"acc_descr_value";case 5:this.begin("acc_descr_multiline");break;case 6:this.popState();break;case 7:return"acc_descr_multiline_value";case 8:break;case 9:break;case 10:break;case 11:return 10;case 12:break;case 13:break;case 14:this.begin("href");break;case 15:this.popState();break;case 16:return 43;case 17:this.begin("callbackname");break;case 18:this.popState();break;case 19:this.popState(),this.begin("callbackargs");break;case 20:return 41;case 21:this.popState();break;case 22:return 42;case 23:this.begin("click");break;case 24:this.popState();break;case 25:return 40;case 26:return 4;case 27:return 22;case 28:return 23;case 29:return 24;case 30:return 25;case 31:return 26;case 32:return 28;case 33:return 27;case 34:return 29;case 35:return 12;case 36:return 13;case 37:return 14;case 38:return 15;case 39:return 16;case 40:return 17;case 41:return 18;case 42:return 20;case 43:return 21;case 44:return"date";case 45:return 30;case 46:return"accDescription";case 47:return 36;case 48:return 38;case 49:return 39;case 50:return":";case 51:return 6;case 52:return"INVALID"}},"anonymous"),rules:[/^(?:%%\{)/i,/^(?:accTitle\s*:\s*)/i,/^(?:(?!\n||)*[^\n]*)/i,/^(?:accDescr\s*:\s*)/i,/^(?:(?!\n||)*[^\n]*)/i,/^(?:accDescr\s*\{\s*)/i,/^(?:[\}])/i,/^(?:[^\}]*)/i,/^(?:%%(?!\{)*[^\n]*)/i,/^(?:[^\}]%%*[^\n]*)/i,/^(?:%%*[^\n]*[\n]*)/i,/^(?:[\n]+)/i,/^(?:\s+)/i,/^(?:%[^\n]*)/i,/^(?:href[\s]+["])/i,/^(?:["])/i,/^(?:[^"]*)/i,/^(?:call[\s]+)/i,/^(?:\([\s]*\))/i,/^(?:\()/i,/^(?:[^(]*)/i,/^(?:\))/i,/^(?:[^)]*)/i,/^(?:click[\s]+)/i,/^(?:[\s\n])/i,/^(?:[^\s\n]*)/i,/^(?:gantt\b)/i,/^(?:dateFormat\s[^#\n;]+)/i,/^(?:inclusiveEndDates\b)/i,/^(?:topAxis\b)/i,/^(?:axisFormat\s[^#\n;]+)/i,/^(?:tickInterval\s[^#\n;]+)/i,/^(?:includes\s[^#\n;]+)/i,/^(?:excludes\s[^#\n;]+)/i,/^(?:todayMarker\s[^\n;]+)/i,/^(?:weekday\s+monday\b)/i,/^(?:weekday\s+tuesday\b)/i,/^(?:weekday\s+wednesday\b)/i,/^(?:weekday\s+thursday\b)/i,/^(?:weekday\s+friday\b)/i,/^(?:weekday\s+saturday\b)/i,/^(?:weekday\s+sunday\b)/i,/^(?:weekend\s+friday\b)/i,/^(?:weekend\s+saturday\b)/i,/^(?:\d\d\d\d-\d\d-\d\d\b)/i,/^(?:title\s[^\n]+)/i,/^(?:accDescription\s[^#\n;]+)/i,/^(?:section\s[^\n]+)/i,/^(?:[^:\n]+)/i,/^(?::[^#\n;]+)/i,/^(?::)/i,/^(?:$)/i,/^(?:.)/i],conditions:{acc_descr_multiline:{rules:[6,7],inclusive:!1},acc_descr:{rules:[4],inclusive:!1},acc_title:{rules:[2],inclusive:!1},callbackargs:{rules:[21,22],inclusive:!1},callbackname:{rules:[18,19,20],inclusive:!1},href:{rules:[15,16],inclusive:!1},click:{rules:[24,25],inclusive:!1},INITIAL:{rules:[0,1,3,5,8,9,10,11,12,13,14,17,23,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52],inclusive:!0}}};return T}();k.lexer=b;function p(){this.yy={}}return l(p,"Parser"),p.prototype=k,k.Parser=p,new p}();Lt.parser=Lt;var Sr=Lt;U.extend(cr);U.extend(br);U.extend(wr);var ce={friday:5,saturday:6},tt="",Vt="",zt=void 0,Rt="",dt=[],ft=[],Nt=new Map,Ht=[],Dt=[],ht="",Bt="",me=["active","done","crit","milestone","vert"],Gt=[],ct="",gt=!1,jt=!1,Ut="sunday",St="saturday",Ot=0,Mr=l(function(){Ht=[],Dt=[],ht="",Gt=[],wt=0,Pt=void 0,_t=void 0,B=[],tt="",Vt="",Bt="",zt=void 0,Rt="",dt=[],ft=[],gt=!1,jt=!1,Ot=0,Nt=new Map,ct="",Oe(),Ut="sunday",St="saturday"},"clear"),Cr=l(function(t){ct=t},"setDiagramId"),Er=l(function(t){Vt=t},"setAxisFormat"),Ir=l(function(){return Vt},"getAxisFormat"),Yr=l(function(t){zt=t},"setTickInterval"),Ar=l(function(){return zt},"getTickInterval"),$r=l(function(t){Rt=t},"setTodayMarker"),Fr=l(function(){return Rt},"getTodayMarker"),Lr=l(function(t){tt=t},"setDateFormat"),Or=l(function(){gt=!0},"enableInclusiveEndDates"),Wr=l(function(){return gt},"endDatesAreInclusive"),Pr=l(function(){jt=!0},"enableTopAxis"),Vr=l(function(){return jt},"topAxisEnabled"),zr=l(function(t){Bt=t},"setDisplayMode"),Rr=l(function(){return Bt},"getDisplayMode"),Nr=l(function(){return tt},"getDateFormat"),ke=l((t,e)=>{const r=e.toLowerCase().split(/[\s,]+/).filter(n=>n!=="");return[...new Set([...t,...r])]},"mergeTokens"),Hr=l(function(t){dt=ke(dt,t)},"setIncludes"),Br=l(function(){return dt},"getIncludes"),Gr=l(function(t){ft=ke(ft,t)},"setExcludes"),jr=l(function(){return ft},"getExcludes"),Ur=l(function(){return Nt},"getLinks"),Xr=l(function(t){ht=t,Ht.push(t)},"addSection"),qr=l(function(){return Ht},"getSections"),Zr=l(function(){let t=le();const e=10;let r=0;for(;!t&&r<e;)t=le(),r++;return Dt=B,Dt},"getTasks"),ye=l(function(t,e,r,n){const s=t.format(e.trim()),o=t.format("YYYY-MM-DD");return n.includes(s)||n.includes(o)?!1:r.includes("weekends")&&(t.isoWeekday()===ce[St]||t.isoWeekday()===ce[St]+1)||r.includes(t.format("dddd").toLowerCase())?!0:r.includes(s)||r.includes(o)},"isInvalidDate"),Qr=l(function(t){Ut=t},"setWeekday"),Kr=l(function(){return Ut},"getWeekday"),Jr=l(function(t){St=t},"setWeekend"),ge=l(function(t,e,r,n){if(!r.length||t.manualEndTime)return;let s;t.startTime instanceof Date?s=U(t.startTime):s=U(t.startTime,e,!0),s=s.add(1,"d");let o;t.endTime instanceof Date?o=U(t.endTime):o=U(t.endTime,e,!0);const[d,x]=tn(s,o,e,r,n);t.endTime=d.toDate(),t.renderEndTime=x},"checkTaskDates"),tn=l(function(t,e,r,n,s){let o=!1,d=null;const x=e.add(1e4,"d");for(;t<=e;){if(o||(d=e.toDate()),o=ye(t,r,n,s),o&&(e=e.add(1,"d"),e>x))throw new Error("Failed to find a valid date that was not excluded by `excludes` after 10,000 iterations.");t=t.add(1,"d")}return[e,d]},"fixTaskDates"),ve=l(function(t,e){nt.warn(`Gantt: the "${t}" statement references unknown task id(s): ${e.join(", ")}. Make sure the referenced tasks exist and declare an id. Milestones need both an id and a duration, e.g. "Milestone :milestone, m1, 2023-01-01, 0d".`)},"warnAboutUnknownTaskIds"),Wt=l(function(t,e,r){if(r=r.trim(),l(x=>{const v=x.trim();return v==="x"||v==="X"},"isTimestampFormat")(e)&&/^\d+$/.test(r))return new Date(Number(r));const o=/^after\s+(?<ids>[\d\w- ]+)/.exec(r);if(o!==null){let x=null;const v=[],M=o.groups.ids.split(" ").filter(L=>L!=="");for(const L of M){const _=at(L);if(_===void 0){v.push(L);continue}(!x||_.endTime>x.endTime)&&(x=_)}if(v.length>0&&ve("after",v),x)return x.endTime;const D=new Date;return D.setHours(0,0,0,0),D}let d=U(r,e.trim(),!0);if(d.isValid())return d.toDate();{nt.debug("Invalid date:"+r),nt.debug("With date format:"+e.trim());const x=new Date(r);if(x===void 0||isNaN(x.getTime())||x.getFullYear()<-1e4||x.getFullYear()>1e4)throw new Error("Invalid date:"+r);return x}},"getStartDate"),pe=l(function(t){const e=/^(\d+(?:\.\d+)?)([Mdhmswy]|ms)$/.exec(t.trim());return e!==null?[Number.parseFloat(e[1]),e[2]]:[NaN,"ms"]},"parseDuration"),Te=l(function(t,e,r,n=!1){r=r.trim();const o=/^until\s+(?<ids>[\d\w- ]+)/.exec(r);if(o!==null){let D=null;const L=[],_=o.groups.ids.split(" ").filter(W=>W!=="");for(const W of _){const O=at(W);if(O===void 0){L.push(W);continue}(!D||O.startTime<D.startTime)&&(D=O)}if(L.length>0&&ve("until",L),D)return D.startTime;const w=new Date;return w.setHours(0,0,0,0),w}let d=U(r,e.trim(),!0);if(d.isValid())return n&&(d=d.add(1,"d")),d.toDate();let x=U(t);const[v,M]=pe(r);if(Number.isNaN(v))nt.warn(`Gantt: "${r}" is neither a valid date for the "${e.trim()}" date format nor a valid duration (e.g. "3d"), so it is ignored and the task gets a zero duration. Milestones need a duration too, e.g. "Milestone :milestone, m1, 2023-01-01, 0d".`);else{const D=x.add(v,M);D.isValid()&&(x=D)}return x.toDate()},"getEndDate"),wt=0,ut=l(function(t){return t===void 0?(wt=wt+1,"task"+wt):t},"parseId"),en=l(function(t,e){let r;e.substr(0,1)===":"?r=e.substr(1,e.length):r=e;const n=r.split(","),s={};Xt(n,s,me);for(let d=0;d<n.length;d++)n[d]=n[d].trim();let o="";switch(n.length){case 1:s.id=ut(),s.startTime=t.endTime,o=n[0];break;case 2:s.id=ut(),s.startTime=Wt(void 0,tt,n[0]),o=n[1];break;case 3:s.id=ut(n[0]),s.startTime=Wt(void 0,tt,n[1]),o=n[2];break}return o&&(s.endTime=Te(s.startTime,tt,o,gt),s.manualEndTime=U(o,"YYYY-MM-DD",!0).isValid(),ge(s,tt,ft,dt)),s},"compileData"),rn=l(function(t,e){let r;e.substr(0,1)===":"?r=e.substr(1,e.length):r=e;const n=r.split(","),s={};Xt(n,s,me);for(let o=0;o<n.length;o++)n[o]=n[o].trim();switch(n.length){case 1:s.id=ut(),s.startTime={type:"prevTaskEnd",id:t},s.endTime={data:n[0]};break;case 2:s.id=ut(),s.startTime={type:"getStartDate",startData:n[0]},s.endTime={data:n[1]};break;case 3:s.id=ut(n[0]),s.startTime={type:"getStartDate",startData:n[1]},s.endTime={data:n[2]};break}return s},"parseData"),Pt,_t,B=[],xe={},nn=l(function(t,e){const r={section:ht,type:ht,processed:!1,manualEndTime:!1,renderEndTime:null,raw:{data:e},task:t,classes:[]},n=rn(_t,e);r.raw.startTime=n.startTime,r.raw.endTime=n.endTime,r.id=n.id,r.prevTaskId=_t,r.active=n.active,r.done=n.done,r.crit=n.crit,r.milestone=n.milestone,r.vert=n.vert,r.vert?r.order=-1:(r.order=Ot,Ot++);const s=B.push(r);_t=r.id,xe[r.id]=s-1},"addTask"),at=l(function(t){const e=xe[t];return B[e]},"findTaskById"),sn=l(function(t,e){const r={section:ht,type:ht,description:t,task:t,classes:[]},n=en(Pt,e);r.startTime=n.startTime,r.endTime=n.endTime,r.id=n.id,r.active=n.active,r.done=n.done,r.crit=n.crit,r.milestone=n.milestone,r.vert=n.vert,Pt=r,Dt.push(r)},"addTaskOrg"),le=l(function(){const t=l(function(r){const n=B[r];let s="";switch(B[r].raw.startTime.type){case"prevTaskEnd":{const o=at(n.prevTaskId);n.startTime=o.endTime;break}case"getStartDate":s=Wt(void 0,tt,B[r].raw.startTime.startData),s&&(B[r].startTime=s);break}return B[r].startTime&&(B[r].endTime=Te(B[r].startTime,tt,B[r].raw.endTime.data,gt),B[r].endTime&&(B[r].processed=!0,B[r].manualEndTime=U(B[r].raw.endTime.data,"YYYY-MM-DD",!0).isValid(),ge(B[r],tt,ft,dt))),B[r].processed},"compileTask");let e=!0;for(const[r,n]of B.entries())t(r),e=e&&n.processed;return e},"compileTasks"),an=l(function(t,e){let r=e;lt().securityLevel!=="loose"&&(r=Le(e)),t.split(",").forEach(function(n){at(n)!==void 0&&(we(n,()=>{window.open(r,"_self")}),Nt.set(n,r))}),be(t,"clickable")},"setLink"),be=l(function(t,e){t.split(",").forEach(function(r){let n=at(r);n!==void 0&&n.classes.push(e)})},"setClass"),on=l(function(t,e,r){if(lt().securityLevel!=="loose"||e===void 0)return;let n=[];if(typeof r=="string"){n=r.split(/,(?=(?:(?:[^"]*"){2})*[^"]*$)/);for(let o=0;o<n.length;o++){let d=n[o].trim();d.startsWith('"')&&d.endsWith('"')&&(d=d.substr(1,d.length-2)),n[o]=d}}n.length===0&&n.push(t),at(t)!==void 0&&we(t,()=>{We.runFunc(e,...n)})},"setClickFun"),we=l(function(t,e){Gt.push(function(){const r=ct?`${ct}-${t}`:t,n=document.querySelector(`[id="${r}"]`);n!==null&&n.addEventListener("click",function(){e()})},function(){const r=ct?`${ct}-${t}`:t,n=document.querySelector(`[id="${r}-text"]`);n!==null&&n.addEventListener("click",function(){e()})})},"pushFun"),cn=l(function(t,e,r){t.split(",").forEach(function(n){on(n,e,r)}),be(t,"clickable")},"setClickEvent"),ln=l(function(t){Gt.forEach(function(e){e(t)})},"bindFunctions"),un={getConfig:l(()=>lt().gantt,"getConfig"),clear:Mr,setDateFormat:Lr,getDateFormat:Nr,enableInclusiveEndDates:Or,endDatesAreInclusive:Wr,enableTopAxis:Pr,topAxisEnabled:Vr,setAxisFormat:Er,getAxisFormat:Ir,setTickInterval:Yr,getTickInterval:Ar,setTodayMarker:$r,getTodayMarker:Fr,setAccTitle:Ae,getAccTitle:Ye,setDiagramTitle:Ie,getDiagramTitle:Ee,setDiagramId:Cr,setDisplayMode:zr,getDisplayMode:Rr,setAccDescription:Ce,getAccDescription:Me,addSection:Xr,getSections:qr,getTasks:Zr,addTask:nn,findTaskById:at,addTaskOrg:sn,setIncludes:Hr,getIncludes:Br,setExcludes:Gr,getExcludes:jr,setClickEvent:cn,setLink:an,getLinks:Ur,bindFunctions:ln,parseDuration:pe,isInvalidDate:ye,setWeekday:Qr,getWeekday:Kr,setWeekend:Jr};function Xt(t,e,r){let n=!0;for(;n;)n=!1,r.forEach(function(s){const o="^\\s*"+s+"\\s*$",d=new RegExp(o);t[0].match(d)&&(e[s]=!0,t.shift(1),n=!0)})}l(Xt,"getTaskTags");U.extend(Dr);var dn=l(function(){nt.debug("Something is calling, setConf, remove the call")},"setConf"),ue={monday:qe,tuesday:Xe,wednesday:Ue,thursday:je,friday:Ge,saturday:Be,sunday:He},fn=l((t,e)=>{let r=[...t].map(()=>-1/0),n=[...t].sort((o,d)=>o.startTime-d.startTime||o.order-d.order),s=0;for(const o of n)for(let d=0;d<r.length;d++)if(o.startTime>=r[d]){r[d]=o.endTime,o.order=d+e,d>s&&(s=d);break}return s},"getMaxIntersections"),rt,$t=1e4,hn=l(function(t,e,r,n){const s=lt().gantt;n.db.setDiagramId(e);const o=lt().securityLevel;let d;o==="sandbox"&&(d=Tt("#i"+e));const x=o==="sandbox"?Tt(d.nodes()[0].contentDocument.body):Tt("body"),v=o==="sandbox"?d.nodes()[0].contentDocument:document,M=v.getElementById(e);rt=M.parentElement.offsetWidth,rt===void 0&&(rt=1200),s.useWidth!==void 0&&(rt=s.useWidth);const D=n.db.getTasks(),L=D.filter(k=>!k.vert);let _=[];for(const k of L)_.push(k.type);_=F(_);const w={};let W=2*s.topPadding;if(n.db.getDisplayMode()==="compact"||s.displayMode==="compact"){const k={};for(const p of L)k[p.section]===void 0?k[p.section]=[p]:k[p.section].push(p);let b=0;for(const p of Object.keys(k)){const T=fn(k[p],b)+1;b+=T,W+=T*(s.barHeight+s.barGap),w[p]=T}}else{W+=L.length*(s.barHeight+s.barGap);for(const k of _)w[k]=L.filter(b=>b.type===k).length}M.setAttribute("viewBox","0 0 "+rt+" "+W);const O=x.select(`[id="${e}"]`),S=Pe().domain([Ve(D,function(k){return k.startTime}),ze(D,function(k){return k.endTime})]).rangeRound([0,rt-s.leftPadding-s.rightPadding]);function z(k,b){const p=k.startTime,T=b.startTime;let a=0;return p>T?a=1:p<T&&(a=-1),a}l(z,"taskCompare"),D.sort(z),X(D,rt,W),$e(O,W,rt,s.useMaxWidth),O.append("text").text(n.db.getDiagramTitle()).attr("x",rt/2).attr("y",s.titleTopMargin).attr("class","titleText");function X(k,b,p){const T=s.barHeight,a=T+s.barGap,h=s.topPadding,y=s.leftPadding,f=Re().domain([0,_.length]).range(["#00B9FA","#F95002"]).interpolate(Ne);G(a,h,y,b,p,k,n.db.getExcludes(),n.db.getIncludes()),C(y,h,b,p),R(k,a,h,y,T,f,b),g(a,h),m(y,h,b,p)}l(X,"makeGantt");function R(k,b,p,T,a,h,y){k.sort((c,E)=>c.vert===E.vert?0:c.vert?1:-1);const f=k.filter(c=>!c.vert),i=[...new Set(f.map(c=>c.order))].map(c=>f.find(E=>E.order===c));O.append("g").selectAll("rect").data(i).enter().append("rect").attr("x",0).attr("y",function(c,E){return E=c.order,E*b+p-2}).attr("width",function(){return y-s.rightPadding/2}).attr("height",b).attr("class",function(c){for(const[E,I]of _.entries())if(c.type===I)return"section section"+E%s.numberSectionStyles;return"section section0"}).enter();const $=O.append("g").selectAll("rect").data(k).enter(),u=n.db.getLinks();if($.append("rect").attr("id",function(c){return e+"-"+c.id}).attr("rx",3).attr("ry",3).attr("x",function(c){return c.milestone?S(c.startTime)+T+.5*(S(c.endTime)-S(c.startTime))-.5*a:S(c.startTime)+T}).attr("y",function(c,E){return E=c.order,c.vert?s.gridLineStartPadding:E*b+p}).attr("width",function(c){return c.milestone?a:c.vert?.08*a:S(c.renderEndTime||c.endTime)-S(c.startTime)}).attr("height",function(c){return c.vert?f.length*(s.barHeight+s.barGap)+s.barHeight*2:a}).attr("transform-origin",function(c,E){return E=c.order,(S(c.startTime)+T+.5*(S(c.endTime)-S(c.startTime))).toString()+"px "+(E*b+p+.5*a).toString()+"px"}).attr("class",function(c){const E="task";let I="";c.classes.length>0&&(I=c.classes.join(" "));let P=0;for(const[N,V]of _.entries())c.type===V&&(P=N%s.numberSectionStyles);let Y="";return c.active?c.crit?Y+=" activeCrit":Y=" active":c.done?c.crit?Y=" doneCrit":Y=" done":c.crit&&(Y+=" crit"),Y.length===0&&(Y=" task"),c.milestone&&(Y=" milestone "+Y),c.vert&&(Y=" vert "+Y),Y+=P,Y+=" "+I,E+Y}),$.append("text").attr("id",function(c){return e+"-"+c.id+"-text"}).text(function(c){return c.task}).attr("font-size",s.fontSize).attr("x",function(c){let E=S(c.startTime),I=S(c.renderEndTime||c.endTime);if(c.milestone&&(E+=.5*(S(c.endTime)-S(c.startTime))-.5*a,I=E+a),c.vert)return S(c.startTime)+T;const P=this.getBBox().width;return P>I-E?I+P+1.5*s.leftPadding>y?E+T-5:I+T+5:(I-E)/2+E+T}).attr("y",function(c,E){return c.vert?s.gridLineStartPadding+f.length*(s.barHeight+s.barGap)+60:(E=c.order,E*b+s.barHeight/2+(s.fontSize/2-2)+p)}).attr("text-height",a).attr("class",function(c){const E=S(c.startTime);let I=S(c.endTime);c.milestone&&(I=E+a);const P=this.getBBox().width;let Y="";c.classes.length>0&&(Y=c.classes.join(" "));let N=0;for(const[mt,Mt]of _.entries())c.type===Mt&&(N=mt%s.numberSectionStyles);let V="";return c.active&&(c.crit?V="activeCritText"+N:V="activeText"+N),c.done?c.crit?V=V+" doneCritText"+N:V=V+" doneText"+N:c.crit&&(V=V+" critText"+N),c.milestone&&(V+=" milestoneText"),c.vert&&(V+=" vertText"),P>I-E?I+P+1.5*s.leftPadding>y?Y+" taskTextOutsideLeft taskTextOutside"+N+" "+V:Y+" taskTextOutsideRight taskTextOutside"+N+" "+V+" width-"+P:Y+" taskText taskText"+N+" "+V+" width-"+P}),lt().securityLevel==="sandbox"){let c;c=Tt("#i"+e);const E=c.nodes()[0].contentDocument;$.filter(function(I){return u.has(I.id)}).each(function(I){var P=E.querySelector("#"+CSS.escape(e+"-"+I.id)),Y=E.querySelector("#"+CSS.escape(e+"-"+I.id+"-text"));const N=P.parentNode;var V=E.createElement("a");V.setAttribute("xlink:href",u.get(I.id)),V.setAttribute("target","_top"),N.appendChild(V),V.appendChild(P),V.appendChild(Y)})}}l(R,"drawRects");function G(k,b,p,T,a,h,y,f){if(y.length===0&&f.length===0)return;let A,i;for(const{startTime:I,endTime:P}of h)(A===void 0||I<A)&&(A=I),(i===void 0||P>i)&&(i=P);if(!A||!i)return;if(U(i).diff(U(A),"year")>5){nt.warn("The difference between the min and max time is more than 5 years. This will cause performance issues. Skipping drawing exclude days.");return}const $=n.db.getDateFormat(),u=[];let j=null,c=U(A);for(;c.valueOf()<=i;)n.db.isInvalidDate(c,$,y,f)?j?j.end=c:j={start:c,end:c}:j&&(u.push(j),j=null),c=c.add(1,"d");O.append("g").selectAll("rect").data(u).enter().append("rect").attr("id",I=>e+"-exclude-"+I.start.format("YYYY-MM-DD")).attr("x",I=>S(I.start.startOf("day"))+p).attr("y",s.gridLineStartPadding).attr("width",I=>S(I.end.endOf("day"))-S(I.start.startOf("day"))).attr("height",a-b-s.gridLineStartPadding).attr("transform-origin",function(I,P){return(S(I.start)+p+.5*(S(I.end)-S(I.start))).toString()+"px "+(P*k+.5*a).toString()+"px"}).attr("class","exclude-range")}l(G,"drawExcludeDays");function H(k,b,p,T){if(p<=0||k>b)return 1/0;const a=b-k,h=U.duration({[T??"day"]:p}).asMilliseconds();return h<=0?1/0:Math.ceil(a/h)}l(H,"getEstimatedTickCount");function C(k,b,p,T){const a=n.db.getDateFormat(),h=n.db.getAxisFormat();let y;h?y=h:a==="D"?y="%d":y=s.axisFormat??"%Y-%m-%d";let f=nr(S).tickSize(-T+b+s.gridLineStartPadding).tickFormat(Qt(y));const i=/^([1-9]\d*)(millisecond|second|minute|hour|day|week|month)$/.exec(n.db.getTickInterval()||s.tickInterval);if(i!==null){const $=parseInt(i[1],10);if(isNaN($)||$<=0)nt.warn(`Invalid tick interval value: "${i[1]}". Skipping custom tick interval.`);else{const u=i[2],j=n.db.getWeekday()||s.weekday,c=S.domain(),E=c[0],I=c[1],P=H(E,I,$,u);if(P>$t)nt.warn(`The tick interval "${$}${u}" would generate ${P} ticks, which exceeds the maximum allowed (${$t}). This may indicate an invalid date or time range. Skipping custom tick interval.`);else switch(u){case"millisecond":f.ticks(ne.every($));break;case"second":f.ticks(re.every($));break;case"minute":f.ticks(ee.every($));break;case"hour":f.ticks(te.every($));break;case"day":f.ticks(Jt.every($));break;case"week":f.ticks(ue[j].every($));break;case"month":f.ticks(Kt.every($));break}}}if(O.append("g").attr("class","grid").attr("transform","translate("+k+", "+(T-50)+")").call(f).selectAll("text").style("text-anchor","middle").attr("fill","#000").attr("stroke","none").attr("font-size",10).attr("dy","1em"),n.db.topAxisEnabled()||s.topAxis){let $=rr(S).tickSize(-T+b+s.gridLineStartPadding).tickFormat(Qt(y));if(i!==null){const u=parseInt(i[1],10);if(isNaN(u)||u<=0)nt.warn(`Invalid tick interval value: "${i[1]}". Skipping custom tick interval.`);else{const j=i[2],c=n.db.getWeekday()||s.weekday,E=S.domain(),I=E[0],P=E[1];if(H(I,P,u,j)<=$t)switch(j){case"millisecond":$.ticks(ne.every(u));break;case"second":$.ticks(re.every(u));break;case"minute":$.ticks(ee.every(u));break;case"hour":$.ticks(te.every(u));break;case"day":$.ticks(Jt.every(u));break;case"week":$.ticks(ue[c].every(u));break;case"month":$.ticks(Kt.every(u));break}}}O.append("g").attr("class","grid").attr("transform","translate("+k+", "+b+")").call($).selectAll("text").style("text-anchor","middle").attr("fill","#000").attr("stroke","none").attr("font-size",10)}}l(C,"makeGrid");function g(k,b){let p=0;const T=Object.keys(w).map(a=>[a,w[a]]);O.append("g").selectAll("text").data(T).enter().append(function(a){const h=a[0].split(Fe.lineBreakRegex),y=-(h.length-1)/2,f=v.createElementNS("http://www.w3.org/2000/svg","text");f.setAttribute("dy",y+"em");for(const[A,i]of h.entries()){const $=v.createElementNS("http://www.w3.org/2000/svg","tspan");$.setAttribute("alignment-baseline","central"),$.setAttribute("x","10"),A>0&&$.setAttribute("dy","1em"),$.textContent=i,f.appendChild($)}return f}).attr("x",10).attr("y",function(a,h){if(h>0)for(let y=0;y<h;y++)return p+=T[h-1][1],a[1]*k/2+p*k+b;else return a[1]*k/2+b}).attr("font-size",s.sectionFontSize).attr("class",function(a){for(const[h,y]of _.entries())if(a[0]===y)return"sectionTitle sectionTitle"+h%s.numberSectionStyles;return"sectionTitle"})}l(g,"vertLabels");function m(k,b,p,T){const a=n.db.getTodayMarker();if(a==="off")return;const h=O.append("g").attr("class","today"),y=new Date,f=h.append("line");f.attr("x1",S(y)+k).attr("x2",S(y)+k).attr("y1",s.titleTopMargin).attr("y2",T-s.titleTopMargin).attr("class","today"),a!==""&&f.attr("style",a.replace(/,/g,";"))}l(m,"drawToday");function F(k){const b={},p=[];for(let T=0,a=k.length;T<a;++T)Object.prototype.hasOwnProperty.call(b,k[T])||(b[k[T]]=!0,p.push(k[T]));return p}l(F,"checkUnique")},"draw"),mn={setConf:dn,draw:hn},kn=l(t=>`
  .mermaid-main-font {
        font-family: ${t.fontFamily};
  }

  .exclude-range {
    fill: ${t.excludeBkgColor};
  }

  .section {
    stroke: none;
    opacity: 0.2;
  }

  .section0 {
    fill: ${t.sectionBkgColor};
  }

  .section2 {
    fill: ${t.sectionBkgColor2};
  }

  .section1,
  .section3 {
    fill: ${t.altSectionBkgColor};
    opacity: 0.2;
  }

  .sectionTitle0 {
    fill: ${t.titleColor};
  }

  .sectionTitle1 {
    fill: ${t.titleColor};
  }

  .sectionTitle2 {
    fill: ${t.titleColor};
  }

  .sectionTitle3 {
    fill: ${t.titleColor};
  }

  .sectionTitle {
    text-anchor: start;
    font-family: ${t.fontFamily};
  }


  /* Grid and axis */

  .grid .tick {
    stroke: ${t.gridColor};
    opacity: 0.8;
    shape-rendering: crispEdges;
  }

  .grid .tick text {
    font-family: ${t.fontFamily};
    fill: ${t.textColor};
  }

  .grid path {
    stroke-width: 0;
  }


  /* Today line */

  .today {
    fill: none;
    stroke: ${t.todayLineColor};
    stroke-width: 2px;
  }


  /* Task styling */

  /* Default task */

  .task {
    stroke-width: 2;
  }

  .taskText {
    text-anchor: middle;
    font-family: ${t.fontFamily};
  }

  .taskTextOutsideRight {
    fill: ${t.taskTextDarkColor};
    text-anchor: start;
    font-family: ${t.fontFamily};
  }

  .taskTextOutsideLeft {
    fill: ${t.taskTextDarkColor};
    text-anchor: end;
  }


  /* Special case clickable */

  .task.clickable {
    cursor: pointer;
  }

  .taskText.clickable {
    cursor: pointer;
    fill: ${t.taskTextClickableColor} !important;
    font-weight: bold;
  }

  .taskTextOutsideLeft.clickable {
    cursor: pointer;
    fill: ${t.taskTextClickableColor} !important;
    font-weight: bold;
  }

  .taskTextOutsideRight.clickable {
    cursor: pointer;
    fill: ${t.taskTextClickableColor} !important;
    font-weight: bold;
  }


  /* Specific task settings for the sections*/

  .taskText0,
  .taskText1,
  .taskText2,
  .taskText3 {
    fill: ${t.taskTextColor};
  }

  .task0,
  .task1,
  .task2,
  .task3 {
    fill: ${t.taskBkgColor};
    stroke: ${t.taskBorderColor};
  }

  .taskTextOutside0,
  .taskTextOutside2
  {
    fill: ${t.taskTextOutsideColor};
  }

  .taskTextOutside1,
  .taskTextOutside3 {
    fill: ${t.taskTextOutsideColor};
  }


  /* Active task */

  .active0,
  .active1,
  .active2,
  .active3 {
    fill: ${t.activeTaskBkgColor};
    stroke: ${t.activeTaskBorderColor};
  }

  .activeText0,
  .activeText1,
  .activeText2,
  .activeText3 {
    fill: ${t.taskTextDarkColor} !important;
  }


  /* Completed task */

  .done0,
  .done1,
  .done2,
  .done3 {
    stroke: ${t.doneTaskBorderColor};
    fill: ${t.doneTaskBkgColor};
    stroke-width: 2;
  }

  .doneText0,
  .doneText1,
  .doneText2,
  .doneText3 {
    fill: ${t.taskTextDarkColor} !important;
  }

  /* Done task text displayed outside the bar sits against the diagram background,
     not against the done-task bar, so it must use the outside/contrast color. */
  .doneText0.taskTextOutsideLeft,
  .doneText0.taskTextOutsideRight,
  .doneText1.taskTextOutsideLeft,
  .doneText1.taskTextOutsideRight,
  .doneText2.taskTextOutsideLeft,
  .doneText2.taskTextOutsideRight,
  .doneText3.taskTextOutsideLeft,
  .doneText3.taskTextOutsideRight {
    fill: ${t.taskTextOutsideColor} !important;
  }


  /* Tasks on the critical line */

  .crit0,
  .crit1,
  .crit2,
  .crit3 {
    stroke: ${t.critBorderColor};
    fill: ${t.critBkgColor};
    stroke-width: 2;
  }

  .activeCrit0,
  .activeCrit1,
  .activeCrit2,
  .activeCrit3 {
    stroke: ${t.critBorderColor};
    fill: ${t.activeTaskBkgColor};
    stroke-width: 2;
  }

  .doneCrit0,
  .doneCrit1,
  .doneCrit2,
  .doneCrit3 {
    stroke: ${t.critBorderColor};
    fill: ${t.doneTaskBkgColor};
    stroke-width: 2;
    cursor: pointer;
    shape-rendering: crispEdges;
  }

  .milestone {
    transform: rotate(45deg) scale(0.8,0.8);
  }

  .milestoneText {
    font-style: italic;
  }
  .doneCritText0,
  .doneCritText1,
  .doneCritText2,
  .doneCritText3 {
    fill: ${t.taskTextDarkColor} !important;
  }

  /* Done-crit task text outside the bar — same reasoning as doneText above. */
  .doneCritText0.taskTextOutsideLeft,
  .doneCritText0.taskTextOutsideRight,
  .doneCritText1.taskTextOutsideLeft,
  .doneCritText1.taskTextOutsideRight,
  .doneCritText2.taskTextOutsideLeft,
  .doneCritText2.taskTextOutsideRight,
  .doneCritText3.taskTextOutsideLeft,
  .doneCritText3.taskTextOutsideRight {
    fill: ${t.taskTextOutsideColor} !important;
  }

  .vert {
    stroke: ${t.vertLineColor};
  }

  .vertText {
    font-size: 15px;
    text-anchor: middle;
    fill: ${t.vertLineColor} !important;
  }

  .activeCritText0,
  .activeCritText1,
  .activeCritText2,
  .activeCritText3 {
    fill: ${t.taskTextDarkColor} !important;
  }

  .titleText {
    text-anchor: middle;
    font-size: 18px;
    fill: ${t.titleColor||t.textColor};
    font-family: ${t.fontFamily};
  }
`,"getStyles"),yn=kn,xn={parser:Sr,db:un,renderer:mn,styles:yn};export{xn as diagram};

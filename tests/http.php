<?php
declare(strict_types=1);
require dirname(__DIR__).'/app/bootstrap.php';
$directory=sys_get_temp_dir().'/box2-http-'.bin2hex(random_bytes(6));mkdir($directory,0700,true);
$socket=stream_socket_server('tcp://127.0.0.1:0',$number,$message);
if (!$socket) throw new RuntimeException('Cannot bind local test socket: '.$message);
$address=stream_socket_get_name($socket,false);fclose($socket);
$base='http://'.$address;
$settings=['storage_path'=>$directory,'base_url'=>$base,'secret'=>str_repeat('t',64),
    'admin_password_hash'=>password_hash('synthetic-host-password',PASSWORD_DEFAULT),'environment'=>'local',
    'allow_bookings'=>true,'venue_public_enabled'=>true,'mail_transport'=>'disabled']+config();
config($settings);migrate();
$night=schedule_night('2030-10-11');
$slots=availability($night);
$configFile=$directory.'/test-config.php';
file_put_contents($configFile,"<?php return ".var_export($settings,true).';');chmod($configFile,0600);
$environment=getenv();$environment['BOX2_CONFIG']=$configFile;
$server=proc_open([PHP_BINARY,'-S',$address,'-t',dirname(__DIR__).'/public',dirname(__DIR__).'/public/router.php'],
    [0=>['pipe','r'],1=>['file',$directory.'/server.log','a'],2=>['file',$directory.'/server.log','a']],$pipes,null,$environment);
if (!is_resource($server)) throw new RuntimeException('Cannot start PHP test server.');
$cookie='';$checks=0;
function http_check(bool $ok,string $label): void {global $checks;if(!$ok) throw new RuntimeException('FAIL: '.$label);$checks++;echo "PASS {$label}\n";}
function request(string $path,?array $data=null): array {
    global $base,$cookie;
    $header='Cookie: '.$cookie."\r\n";
    if($data!==null) $header.="Content-Type: application/x-www-form-urlencoded\r\n";
    $context=stream_context_create(['http'=>['method'=>$data===null?'GET':'POST','header'=>$header,
        'content'=>$data===null?'':http_build_query($data),'ignore_errors'=>true,'follow_location'=>0,'timeout'=>5]]);
    $body=file_get_contents($base.$path,false,$context);
    $headers=$http_response_header??[];
    foreach($headers as $line) if(preg_match('/^Set-Cookie: ([^;]+)/i',$line,$match)) $cookie=$match[1];
    preg_match('/\s(\d{3})\s/',$headers[0]??'',$code);
    return ['code'=>(int)($code[1]??0),'body'=>$body?:'','headers'=>$headers];
}
function form_csrf(array $response): string {
    preg_match('/name="csrf" value="([a-f0-9]+)"/',$response['body'],$match);
    if(!isset($match[1])) throw new RuntimeException('CSRF field missing.');
    return $match[1];
}
try {
    for($attempt=0;$attempt<50;$attempt++) {
        $probe=@fsockopen('127.0.0.1',(int)explode(':',$address)[1],$errno,$error,.1);
        if($probe) {fclose($probe);break;}usleep(20000);
    }
    $home=request('/');http_check($home['code']===200,'home renders on real PHP server');
    http_check(!str_contains($home['body'],$settings['secret']),'secret absent from public HTML');
    http_check(str_contains(implode(' ',$home['headers']),"script-src 'self'"),'CSP disables inline script injection');
    http_check(str_contains(implode(' ',$home['headers']),'HttpOnly'),'session cookie HttpOnly');
    $book=request('/book?night='.$night);$csrf=form_csrf($book);
    http_check($book['code']===200 && str_contains($book['body'],'data-orientation'),'booking renders accessible orientation');
    http_check(!str_contains($book['body'],'onclick='),'no inline onclick-dependent onboarding');
    $data=['csrf'=>$csrf,'slot_id'=>$slots[0]['id'],'night_id'=>$night,'stage_name'=>'HTTP Synthetic',
        'email'=>'http-synthetic@example.test','performance_type'=>'standup','orientation_agreed'=>'1','orientation_version'=>BOX2_TERMS,'terms_agreed'=>'1',
        'livestream_allowed'=>'1','teleprompter_text'=>'PRIVATE_SCRIPT_SENTINEL'];
    $bad=$data;unset($bad['csrf']);$bad['clips_allowed']='1';$badResponse=request('/book',$bad);
    http_check($badResponse['code']===422,'booking POST rejects missing CSRF');
    http_check(!preg_match('/name="clips_allowed"[^>]*checked/',$badResponse['body']) && !str_contains($badResponse['body'],'PRIVATE_SCRIPT_SENTINEL'),'invalid-CSRF requests cannot preselect grants or restore private form data');
    $save=request('/book',$data);
    http_check($save['code']===200 && str_contains($save['body'],'Your place in the room.'),'HTTP booking completes');
    http_check(str_contains($save['body'],'Email confirmations and reminders are unavailable.'),'disabled email disclosed in actual confirmation');
    http_check(!str_contains($save['body'],'PRIVATE_SCRIPT_SENTINEL'),'private script absent from confirmation');
    http_check(request('/book',$data)['code']===422,'HTTP duplicate booking rejected');
    $longData=$data;$longData['slot_id']=$slots[5]['id'];$longData['duration_minutes']='15';$longData['stage_name']='HTTP Synthetic Long';
    $longSave=request('/book',$longData);
    http_check($longSave['code']===200 && str_contains($longSave['body'],'15 stage minutes') && str_contains($longSave['body'],'30 minutes · 3 adjacent allocations'),'HTTP fifteen-minute receipt distinguishes stage and reservation duration');
    http_check(str_contains($longSave['body'],'Arrival window') && str_contains($longSave['body'],'Check in immediately upon arrival') && str_contains($longSave['body'],'On deck at'),'receipt uses arrival window and on-deck target');
    $api=request('/api/slots?night='.$night);
    http_check($api['code']===200 && !str_contains($api['body'],'http-synthetic') && !str_contains($api['body'],'PRIVATE_SCRIPT_SENTINEL'),'public slots contain no contact/script PII');
    $database=query('SELECT id FROM bookings WHERE slot_id=?',[$slots[0]['id']])->fetchColumn();
    preg_match('#href="([^"]+/respond\?action=confirm[^\"]+)"#',$save['body'],$match);
    $link=html_entity_decode($match[1],ENT_QUOTES);$linkPath=substr($link,strlen($base));
    $preview=request($linkPath);http_check(booking_record($database)['status']==='booked','link GET does not mutate booking (email scanners safe)');
    parse_str(parse_url($linkPath,PHP_URL_QUERY),$actionData);$actionData['csrf']=form_csrf($preview);
    http_check(request('/respond',$actionData)['code']===200 && booking_record($database)['status']==='confirmed','CSRF-protected confirmation link POST');
    http_check(request('/respond',$actionData)['code']===422,'HTTP link replay rejected');
    http_check(request('/admin')['code']===302,'admin redirects anonymous visitors');
    http_check(request('/admin/action',['csrf'=>$csrf,'action'=>'performed','booking_id'=>$database])['code']===302,'anonymous admin POST rejected');
    foreach(['/config.example.php','/config.local.php','/var/box2.sqlite','/app/bootstrap.php','/backups/data.sqlite','/uploads/guess.mp4'] as $path) {
        $response=request($path);http_check($response['code']===404 && !str_contains($response['body'],$settings['secret']),'private path denied '.$path);
    }
    $login=request('/admin/login');$loginToken=form_csrf($login);
    http_check(request('/admin/login',['csrf'=>$loginToken,'password'=>'wrong'])['code']===422,'invalid host password denied');
    $before=$cookie;
    http_check(request('/admin/login',['csrf'=>$loginToken,'password'=>'synthetic-host-password'])['code']===302,'valid host password signs in');
    http_check($before!==$cookie,'session id rotates on login');
    $adminPage=request('/admin?night='.$night);$adminToken=form_csrf($adminPage);
    http_check($adminPage['code']===200 && str_contains($adminPage['body'],'PRIVATE_SCRIPT_SENTINEL'),'private script available to authenticated host only');
    http_check(str_contains($adminPage['body'],'15 minute set') && str_contains($adminPage['body'],'30 calendar minutes') && str_contains($adminPage['body'],'Check in immediately upon arrival'),'host lineup includes full long-set timing and approved arrival policy');
    http_check(request('/admin/action',['csrf'=>$adminToken,'action'=>'slot','slot_id'=>$slots[6]['id'],'night_id'=>$night,'visibility'=>'hold'])['code']===422,'host cannot change an occupied tail allocation');
    http_check(request('/admin/action',['csrf'=>'bad','action'=>'performed','booking_id'=>$database])['code']===422,'admin CSRF forgery rejected');
    $state=request('/admin/action',['csrf'=>$adminToken,'action'=>'recording','night_id'=>$night,'mode'=>'public']);
    http_check($state['code']===302,'host records actual broadcast acknowledgment');
    http_check(request('/admin/action',['csrf'=>$adminToken,'action'=>'checked_in','booking_id'=>$database,'night_id'=>$night])['code']===422,'live-only check-in requires explicit VOD/recording acknowledgment');
    $checkin=request('/admin/action',['csrf'=>$adminToken,'action'=>'checked_in','booking_id'=>$database,'night_id'=>$night,'no_archive_confirmed'=>'1']);
    http_check($checkin['code']===302 && booking_record($database)['status']==='checked_in','real host check-in persists');
    $writers=request('/writers');$writerToken=form_csrf($writers);
    $writer=request('/writers',['csrf'=>$writerToken,'alias'=>'Synthetic Writer','text'=>'PRIVATE_WRITER_SENTINEL<script>alert(1)</script>','terms_agreed'=>'1']);
    http_check($writer['code']===200 && str_contains($writer['body'],'Received privately.') && !str_contains($writer['body'],'PRIVATE_WRITER_SENTINEL'),'private writer receipt does not publish text');
    $desk=request('/admin?night='.$night);http_check(str_contains($desk['body'],'&lt;script&gt;alert(1)&lt;/script&gt;'),'stored XSS escaped in host view');
    $logout=request('/admin/logout',['csrf'=>form_csrf($desk)]);
    http_check($logout['code']===302 && request('/admin')['code']===302,'logout revokes host session');
    // Render a separately configured subpath and verify front controller + static assets.
    $settings['base_url']=$base.'/box2';
    file_put_contents($configFile,"<?php return ".var_export($settings,true).';');
    $mounted=request('/box2/book?night='.$night);
    http_check($mounted['code']===200 && str_contains($mounted['body'],$base.'/box2/assets/site.js'),'configured base path renders correct routes and asset URLs');
    http_check(request('/box2/assets/site.js')['code']===200,'base-path JavaScript is served');
    $permalink=request('/box2/book?show=2030-10-11');
    http_check($permalink['code']===200 && str_contains($permalink['body'],'Show evening 2030-10-11')
        && str_contains($permalink['body'],$base.'/box2/book?show=2030-10-11'),'show-date permalink and event metadata are canonical');
    $throttledLogin=request('/box2/admin/login');$throttledCsrf=form_csrf($throttledLogin);
    for($i=0;$i<3;$i++) request('/box2/admin/login',['csrf'=>$throttledCsrf,'password'=>'synthetic-wrong']);
    http_check(request('/box2/admin/login',['csrf'=>$throttledCsrf,'password'=>'synthetic-wrong'])['code']===429,'host login brute-force attempts are throttled');
    $settings['allow_bookings']=false;$settings['venue_public_enabled']=false;
    $settings['arrival_text']='UNAPPROVED_DIRECTIONS_SENTINEL';
    file_put_contents($configFile,"<?php return ".var_export($settings,true).';');
    $closedPreview=request('/box2/book?show=2030-10-11');
    http_check(str_contains($closedPreview['body'],'schedule preview') && str_contains($closedPreview['body'],'Reservations are not open yet'),'disabled booking configuration is honestly labelled as preview');
    $arrival=request('/box2/arrival');$oldArrival=request('/box2/arrive');
    http_check($arrival['code']===200 && $oldArrival['code']===200 && !str_contains($arrival['body'],'UNAPPROVED_DIRECTIONS_SENTINEL') && !str_contains($arrival['body'],$settings['venue_address']),'arrival aliases withhold unapproved address and directions');
    http_check(!str_contains(request('/box2/')['body'],'href="'.$base.'/box2/arrival"'),'unapproved arrival page is not advertised in navigation');
    foreach(['/box2/rules','/box2/book?show=2030-10-11','/box2/arrival'] as $path) {
        $copy=request($path)['body'];
        http_check(!preg_match('/Jerzee|gravel lot|Poetry|reminders on|Best jokes will|Check in 20 minutes before/i',$copy),'deprecated public copy absent '.$path);
    }
    $closedData=$longData;$closedData['csrf']=form_csrf($closedPreview);
    http_check(request('/box2/book',$closedData)['code']===503,'closed launch gates deny even a valid-CSRF booking POST');
    echo "{$checks} HTTP checks passed. Synthetic artifacts: {$directory}\n";
} finally {proc_terminate($server);proc_close($server);}

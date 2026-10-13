<?php
declare(strict_types=1);
require dirname(__DIR__).'/app/bootstrap.php';require __DIR__.'/capture-fixture.php';
$directory=sys_get_temp_dir().'/box2-p1-'.bin2hex(random_bytes(6));mkdir($directory,0700,true);
config(['storage_path'=>$directory,'secret'=>str_repeat('p',64),'environment'=>'local','allow_bookings'=>true,'venue_public_enabled'=>true]);
$_SERVER['REMOTE_ADDR']='127.0.0.1';$_SESSION=['admin'=>true,'last_active'=>time()];migrate();$checks=0;
function pcheck(bool $ok,string $label):void {global $checks;if(!$ok) throw new RuntimeException('FAIL: '.$label);$checks++;echo "PASS {$label}\n";}
function preject(callable $work,string $label):void {try{$work();}catch(InvalidArgumentException|RuntimeException $e){pcheck(true,$label);return;}pcheck(false,$label);}
function pdata(int $slot,bool $private=false,int $minutes=5):array {
    return ['slot_id'=>$slot,'duration_minutes'=>$minutes,'stage_name'=>$private?'PRIVATE_GUEST_SENTINEL':'Synthetic Public Comic','full_name'=>'LEGAL_SENTINEL',
        'email'=>'synthetic@example.test','teleprompter_text'=>'SCRIPT_SENTINEL','performance_type'=>'standup','orientation_agreed'=>1,'orientation_version'=>BOX2_TERMS,'terms_agreed'=>1]
        +($private?[]:['livestream_allowed'=>1,'archive_allowed'=>1,'clips_allowed'=>1]);
}
function candidate_data(string $booking,string $origin='performer_original',string $writer=''):array {
    return ['booking_id'=>$booking,'week_date'=>'2030-10-07','source_reference'=>'Synthetic permitted source reference','source_duration'=>'00:05:00',
        'in_time'=>'00:00:10.000','out_time'=>'00:00:20.500','title'=>'Synthetic moment','origin'=>$origin,'writer_id'=>$writer,'source_verified'=>1,'layers_cleared'=>1];
}
function grant_candidate(string $id,string $role='performer',array $extra=[]):array {
    parse_str(parse_url(editorial_link($id,$role),PHP_URL_QUERY),$fields);
    return apply_editorial_release($extra+['scope_acknowledged'=>1,'face_voice'=>1]+array_fill_keys(array_keys(TOP5_PLATFORMS),1)+$fields);
}
$night=schedule_night('2030-10-11');$slots=availability($night);query("UPDATE slots SET visibility='private' WHERE id=?",[$slots[27]['id']]);
$before=json_encode(booking_options($night));$private=create_booking(pdata($slots[27]['id'],true,15));
pcheck((int)query('SELECT count(*) FROM booking_allocations WHERE booking_id=? AND active=1',[$private['booking']['id']])->fetchColumn()===3,'normal private fifteen-minute booking reserves three blocks');
$after=json_encode(booking_options($night));pcheck($before===$after,'public nonpublic inventory is unchanged by private booking');
pcheck(!str_contains($after,'PRIVATE_GUEST_SENTINEL')&&!str_contains($after,'private')&&!str_contains($after,'visibility')&&!str_contains($after,'SCRIPT_SENTINEL'),'public projection has no private identity/classification/script');
preject(fn()=>host_booking_action($private['booking']['id'],'checked_in'),'private check-in fails closed before source verification');
preject(fn()=>set_capture_state($night,['source'=>'house']+synthetic_house_checks()),'house continuity is disabled by default');
pcheck(!private_capture_safe(query('SELECT * FROM show_nights WHERE id=?',[$night])->fetch()),'failed source assertion invalidates earlier evidence');
set_recording_mode($night,'public',synthetic_stage_checks());config(['allow_house_continuity'=>true]+config());
set_capture_state($night,['source'=>'house']+synthetic_house_checks());host_booking_action($private['booking']['id'],'checked_in');
$state=query('SELECT * FROM show_nights WHERE id=?',[$night])->fetch();
pcheck($state['broadcast_source']==='house'&&$state['room_transmission']==='off'&&$state['room_recording']==='off','channel house program is independent of private room transmission/storage');
preject(fn()=>set_recording_mode($night,'public'),'stage sources cannot resume while private guest remains');
set_capture_state($night,['source'=>'fault']);preject(fn()=>host_booking_action($private['booking']['id'],'checked_in'),'fault/restart invalidates verification instead of reconnecting sources');
foreach(array_keys(ROOM_OFF_CHECKS+HOUSE_CHECKS) as $key) {
    $incomplete=synthetic_house_checks();unset($incomplete[$key]);
    preject(fn()=>set_capture_state($night,['source'=>'house']+$incomplete),'missing '.$key.' fails closed');
    pcheck(!private_capture_safe(query('SELECT * FROM show_nights WHERE id=?',[$night])->fetch()),'failed assertion does not retain an old safe state');
}
set_capture_state($night,['source'=>'house']+synthetic_house_checks());$_SESSION['csrf']=bin2hex(random_bytes(32));
preject(fn()=>host_booking_action($private['booking']['id'],'checked_in'),'new operator session cannot reuse capture assertions');
set_capture_state($night,['source'=>'house']+synthetic_house_checks());query('UPDATE show_nights SET capture_verified_at=? WHERE id=?',['2000-01-01T00:00:00Z',$night]);
preject(fn()=>host_booking_action($private['booking']['id'],'checked_in'),'expired verification fails closed');
set_recording_mode($night,'confirmed_off',synthetic_off_checks());
preject(fn()=>create_editorial_candidate(candidate_data($private['booking']['id'])),'private material cannot enter editorial ledger');
host_booking_action($private['booking']['id'],'cancelled');preject(fn()=>set_recording_mode($night,'public'),'cancellation does not certify physical guest departure');
clear_private_room($night,['guest_left'=>1,'capture_zone_clear'=>1]);set_recording_mode($night,'public',synthetic_stage_checks());
pcheck(availability($night)[27]['state']==='available'&&availability($night)[29]['state']==='available','private cancellation still releases the entire booking range');
$privatePerformed=create_booking(pdata($slots[27]['id'],true));host_booking_action($privatePerformed['booking']['id'],'performed');
preject(fn()=>create_editorial_candidate(candidate_data($privatePerformed['booking']['id'])),'even a performed private set cannot become a recorded candidate');
$liveData=pdata($slots[8]['id']);unset($liveData['archive_allowed'],$liveData['clips_allowed']);$liveOnly=create_booking($liveData);host_booking_action($liveOnly['booking']['id'],'performed');
preject(fn()=>create_editorial_candidate(candidate_data($liveOnly['booking']['id'])),'performed live-only set cannot become a Top 5 candidate');
$public=create_booking(pdata($slots[0]['id']));host_booking_action($public['booking']['id'],'performed');$candidate=create_editorial_candidate(candidate_data($public['booking']['id']));
preject(fn()=>review_editorial_candidate($candidate,'approved'),'generic old clip flag is not a specific Top 5 release');
grant_candidate($candidate,'performer',['youtube'=>0,'credit_allowed'=>0,'public_credit'=>'DO_NOT_CREDIT']);
preject(fn()=>review_editorial_candidate($candidate,'approved'),'one missing destination prevents cross-platform selection');
$grant=query('SELECT * FROM editorial_grants WHERE candidate_id=?',[$candidate])->fetch();pcheck($grant['public_credit']===''&&$grant['public_handle']==='','unpermitted credit never falls back to name or posted text');
$approved=[];$withdrawals=[];
for($index=0;$index<6;$index++) {
    if($index===0) $id=$candidate;
    else {$b=create_booking(pdata($slots[$index]['id']));host_booking_action($b['booking']['id'],'performed');$id=create_editorial_candidate(candidate_data($b['booking']['id']));}
    $withdrawals[$id]=grant_candidate($id,'performer',['credit_allowed'=>1,'public_credit'=>'Approved Synthetic '.$index]);review_editorial_candidate($id,'approved');$approved[]=$id;
    if($index<5) select_top5($id,$index+1);
}
pcheck((int)query('SELECT count(*) FROM weekly_selections')->fetchColumn()===5,'five expressly authorized moments can be selected');
preject(fn()=>select_top5($approved[5],6),'sixth moment blocked by five-position limit');preject(fn()=>select_top5($approved[5],5),'occupied position cannot silently replace another performer');
unselect_top5($approved[1]);select_top5($approved[1],2);
preject(fn()=>record_top5_post('2030-10-07','youtube','https://www.youtube.com/shorts/synthetic'),'posting URL requires a reviewed manual edit');
edited_top5('2030-10-07',['master_reference'=>'Synthetic vertical master','master_rights_reviewed'=>1,'preview_reviewed'=>1]);
foreach(['tiktok'=>'https://www.tiktok.com/@synthetic/video/123','instagram'=>'https://www.instagram.com/reel/synthetic/','facebook'=>'https://www.facebook.com/reel/123','youtube'=>'https://www.youtube.com/shorts/synthetic'] as $platform=>$url) record_top5_post('2030-10-07',$platform,$url);
pcheck((int)query('SELECT count(*) FROM weekly_posts')->fetchColumn()===4,'four manual organic post URLs are recorded, no posting API used');
preject(fn()=>record_top5_post('2030-10-07','youtube','https://youtube.com.evil.test/shorts/fake'),'deceptive external destination rejected');preject(fn()=>unselect_top5($approved[0]),'posted selection history cannot be erased');
parse_str(parse_url($withdrawals[$approved[0]]['withdrawal'],PHP_URL_QUERY),$fields);apply_editorial_release($fields);
pcheck((int)query('SELECT count(*) FROM weekly_posts WHERE removal_requested=1')->fetchColumn()===4,'post-publication withdrawal requests manual removal without promising erasure');
preject(fn()=>record_top5_post('2030-10-07','youtube','https://www.youtube.com/shorts/other'),'withdrawn rights prevent further publication assertions');
$writer=submit_writer(['alias'=>'Synthetic Writer','text'=>'Original line','terms_agreed'=>1]);$wb=create_booking(pdata($slots[6]['id']));host_booking_action($wb['booking']['id'],'performed');
$writerData=candidate_data($wb['booking']['id'],'writer_submission',$writer['id']);$writerData['week_date']='2030-10-14';$writerCandidate=create_editorial_candidate($writerData);grant_candidate($writerCandidate);
preject(fn()=>review_editorial_candidate($writerCandidate,'approved'),'writer-derived material denied without writer base grants');query('UPDATE writer_submissions SET perform_allowed=1,publish_allowed=1 WHERE id=?',[$writer['id']]);
preject(fn()=>review_editorial_candidate($writerCandidate,'approved'),'writer base grants do not imply cross-platform compilation permission');
grant_candidate($writerCandidate,'writer',['credit_allowed'=>1,'public_credit'=>'Writer Preferred Credit']);
grant_candidate($writerCandidate,'performer',['face_voice'=>0]);preject(fn()=>review_editorial_candidate($writerCandidate,'approved'),'destination grants do not imply performer face/voice permission');
grant_candidate($writerCandidate);review_editorial_candidate($writerCandidate,'approved');select_top5($writerCandidate,1);
pcheck((int)query('SELECT count(*) FROM weekly_selections WHERE week_date=?',['2030-10-14'])->fetchColumn()===1,'underlying writer-specific grant allows an authorized moment');
parse_str(parse_url(editorial_link($writerCandidate,'performer'),PHP_URL_QUERY),$own);$spoof=$own+['candidate_id'=>$approved[1],'role'=>'writer','scope_acknowledged'=>1,'public_credit'=>'Other credit'];apply_editorial_release($spoof);
pcheck(query('SELECT public_credit FROM editorial_grants WHERE candidate_id=? AND role=?',[$approved[1],'performer'])->fetchColumn()==='Approved Synthetic 1','capability cannot alter another performer credit or role');
preject(fn()=>apply_editorial_release($spoof),'one-use release token cannot be replayed');$forged=$own;$forged['signature']=str_repeat('0',64);preject(fn()=>editorial_authorization($forged),'forged editorial release denied');
parse_str(parse_url(editorial_link($writerCandidate,'writer'),PHP_URL_QUERY),$oldScope);
query('UPDATE editorial_tokens SET version=? WHERE token_hash=?',['older-scope',hash('sha256',$oldScope['token'])]);
preject(fn()=>editorial_authorization($oldScope),'older-scope capability cannot silently grant current publication terms');
$_SESSION=[];preject(fn()=>select_top5($approved[5],1),'editorial modification denied without host auth');pcheck(query('PRAGMA integrity_check')->fetchColumn()==='ok','P1 database integrity');
echo "{$checks} privacy/capture/editorial checks passed. Automated tests do not certify OBS or camera hardware.\n";

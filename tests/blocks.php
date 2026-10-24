<?php
declare(strict_types=1);
require dirname(__DIR__).'/app/bootstrap.php';
$directory=sys_get_temp_dir().'/box2-blocks-'.bin2hex(random_bytes(6));mkdir($directory,0700,true);
config(['storage_path'=>$directory,'secret'=>str_repeat('b',64),'environment'=>'local','allow_bookings'=>true,'venue_public_enabled'=>true]);
$_SERVER['REMOTE_ADDR']='127.0.0.1';$_SESSION=['admin'=>true,'last_active'=>time()];migrate();
$checks=0;
function blocks_check(bool $ok,string $label): void {global $checks;if(!$ok) throw new RuntimeException('FAIL: '.$label);$checks++;echo "PASS {$label}\n";}
function blocks_reject(callable $work,string $label): void {try{$work();}catch(InvalidArgumentException $exception){blocks_check(true,$label);return;}blocks_check(false,$label);}
function block_payload(int $slot,int $minutes=5,bool $private=false): array {
    return ['slot_id'=>$slot,'duration_minutes'=>$minutes,'stage_name'=>'Synthetic Block Comic','email'=>'blocks@example.test',
        'performance_type'=>'standup','orientation_agreed'=>'1','orientation_version'=>BOX2_TERMS,'terms_agreed'=>'1']
        +($private?[]:['livestream_allowed'=>'1']);
}
function cancel_block(array $result): void {parse_str(parse_url($result['links']['cancel'],PHP_URL_QUERY),$data);apply_booking_link($data);}
$night=schedule_night('2030-10-11');$slots=availability($night);
blocks_check($slots[0]['durations']===[5,10,15],'empty consecutive public allocations offer all set lengths');
blocks_check($slots[20]['durations']===[5,10] && $slots[21]['durations']===[5],'held boundary removes lengths that do not fit');
blocks_check($slots[28]['durations']===[5,10] && $slots[29]['durations']===[5],'private end-of-show length options are real');
foreach([5=>0,10=>3,15=>7] as $minutes=>$start) {
    $result=create_booking(block_payload($slots[$start]['id'],$minutes));$booking=$result['booking'];
    $allocated=query('SELECT slot_id FROM booking_allocations WHERE booking_id=? AND active=1 ORDER BY slot_id',[$booking['id']])->fetchAll(PDO::FETCH_COLUMN);
    blocks_check(count($allocated)===$minutes/5 && $booking['block_count']===$minutes/5,'stage '.$minutes.' minutes reserves the correct adjacent allocation count');
    blocks_check($booking['duration_minutes']===$minutes,'stage duration is stored');
    blocks_check(strtotime($booking['stage_end_at_utc'])-strtotime($booking['start_at_utc'])===$minutes*60,'stage end is separate from reservation end');
    blocks_check(strtotime($booking['reservation_end_at_utc'])-strtotime($booking['start_at_utc'])===$minutes*120,'calendar reservation retains host/reset buffer');
    foreach(array_slice(availability($night),$start,(int)($minutes/5)) as $slot) blocks_check($slot['state']==='booked','every reserved allocation is unavailable publicly');
    cancel_block($result);
    blocks_check((int)query('SELECT count(*) FROM booking_allocations WHERE booking_id=? AND active=1',[$booking['id']])->fetchColumn()===0,'cancellation releases the entire '.$minutes.'-minute set');
    blocks_check((int)query('SELECT count(*) FROM booking_allocations WHERE booking_id=?',[$booking['id']])->fetchColumn()===$minutes/5,'cancelled allocation history is retained');
}
$long=create_booking(block_payload($slots[2]['id'],15));
$before=(int)query('SELECT count(*) FROM bookings')->fetchColumn();
blocks_reject(fn()=>create_booking(block_payload($slots[1]['id'],10)),'overlap with another booking tail is rejected');
blocks_reject(fn()=>create_booking(block_payload($slots[4]['id'],15)),'overlap with another booking middle is rejected');
blocks_check((int)query('SELECT count(*) FROM bookings')->fetchColumn()===$before,'overlap failures leave no partial booking');
blocks_check(availability($night)[1]['durations']===[5],'length availability reflects an occupied adjacent allocation');
cancel_block($long);
query("UPDATE slots SET status='closed' WHERE id=?",[$slots[1]['id']]);
blocks_check(availability($night)[0]['durations']===[5],'closed middle allocation removes longer options');
blocks_reject(fn()=>create_booking(block_payload($slots[0]['id'],15)),'server rejects a closed middle allocation');
query("UPDATE slots SET status='open' WHERE id=?",[$slots[1]['id']]);
blocks_reject(fn()=>create_booking(block_payload($slots[21]['id'],10)),'public set cannot cross into held blocks');
blocks_reject(fn()=>create_booking(block_payload($slots[29]['id'],10,true)),'set cannot run past show end');
blocks_reject(fn()=>create_booking(block_payload($slots[0]['id'],20)),'unsupported duration rejected');
$stale=block_payload($slots[0]['id']);$stale['orientation_version']='2026-10-08';
blocks_reject(fn()=>create_booking($stale),'previous-policy acknowledgment cannot satisfy the nine-card release');
foreach(['Music','Poetry','Other','spoken_word','music'] as $invalid) {
    $data=block_payload($slots[0]['id']);$data['performance_type']=$invalid;
    blocks_reject(fn()=>create_booking($data),'non-comedy format '.$invalid.' rejected server-side');
}
foreach(array_keys(BOX2_FORMATS) as $format) {
    $data=block_payload($slots[0]['id']);$data['performance_type']=$format;$result=create_booking($data);
    blocks_check($result['booking']['performance_type']===$format,'approved format '.$format.' accepted');cancel_block($result);
}
$cross=create_booking(block_payload($slots[17]['id'],15));
blocks_check($cross['booking']['show_date']==='2030-10-11' && str_contains(local_label($cross['booking']['stage_end_at_utc']),'Sat Oct 12, 12:05 AM'),'stage set crosses midnight with correct show and actual dates');
blocks_check(str_contains(local_label($cross['booking']['reservation_end_at_utc']),'12:20 AM'),'midnight reservation end includes three full calendar blocks');cancel_block($cross);
$late=create_booking(block_payload($slots[19]['id'],15));$times=arrival_times($late['booking']['start_at_utc']);
blocks_check(str_contains(local_label($times['opens_at_utc']),'Fri Oct 11, 11:50 PM') && str_contains(local_label($times['on_deck_at_utc']),'Sat Oct 12, 12:00 AM'),'arrival window can cross the show midnight correctly');
$body=json_decode(query("SELECT payload FROM reminders WHERE booking_id=? AND type='check_in_30'",[$late['booking']['id']])->fetchColumn(),true)['body'];
blocks_check(str_contains($body,'15 stage minutes') && str_contains($body,'30 minutes across 3') && str_contains($body,'Check in immediately upon arrival') && !str_contains($body,'Check in:'),'reminders include current timing and duration, with no T-20 deadline');
cancel_block($late);
$private=create_booking(block_payload($slots[28]['id'],10,true));
foreach(['livestream','archive','clips','adaptation','feedback'] as $grant) blocks_check($private['booking'][$grant.'_allowed']===0,'private '.$grant.' grant remains default off');
blocks_reject(fn()=>host_booking_action($private['booking']['id'],'checked_in'),'multi-block private rehearsal still requires actual stream-stop acknowledgment');
set_recording_mode($night,'confirmed_off');host_booking_action($private['booking']['id'],'checked_in');
blocks_reject(fn()=>set_recording_mode($night,'public'),'private multi-block check-in still blocks broadcast resumption');
host_booking_action($private['booking']['id'],'cancelled');
blocks_check(availability($night)[28]['state']==='available' && availability($night)[29]['state']==='available','host cancellation releases both private allocations');
$fall=schedule_night('2030-11-02');query("UPDATE slots SET visibility='public' WHERE show_night_id=?",[$fall]);$fallSlots=availability($fall);
$repeated=create_booking(block_payload($fallSlots[29]['id'],15));
blocks_check(str_contains(local_label($repeated['booking']['start_at_utc']),'1:50 AM EDT') && str_contains(local_label($repeated['booking']['stage_end_at_utc']),'1:05 AM EST'),'multi-slot stage range survives fall-back repeated hour');
blocks_check(strtotime($repeated['booking']['reservation_end_at_utc'])-strtotime($repeated['booking']['start_at_utc'])===1800,'fall-back reservation is exactly 30 real minutes');cancel_block($repeated);
if(function_exists('pcntl_fork')) {
    $children=[];
    foreach([0=>[5,15],1=>[7,10]] as $index=>[$start,$minutes]) {
        $pid=pcntl_fork();
        if($pid===0) {
            db(true);usleep(50000);
            try{create_booking(block_payload($slots[$start]['id'],$minutes));$outcome='booked';}
            catch(InvalidArgumentException $exception){$outcome='rejected';}
            catch(Throwable $exception){$outcome='unexpected';}
            file_put_contents($directory.'/race-'.$index,$outcome);exit($outcome==='unexpected'?1:0);
        }
        $children[]=$pid;
    }
    foreach($children as $child) {pcntl_waitpid($child,$status);blocks_check(pcntl_wexitstatus($status)===0,'concurrent range worker completes without SQL errors');}
    $outcomes=[file_get_contents($directory.'/race-0'),file_get_contents($directory.'/race-1')];sort($outcomes);
    blocks_check($outcomes===['booked','rejected'],'different-start concurrent overlapping range requests produce one winner');
} else echo "SKIP overlapping process race: pcntl unavailable.\n";
blocks_check(query('PRAGMA integrity_check')->fetchColumn()==='ok','multi-block database integrity');
echo "{$checks} adjacent-block checks passed.\n";

<?php
declare(strict_types=1);

const BOX2_FORMATS = ['standup' => 'Stand-up', 'musical_comedy' => 'Portable-instrument musical comedy',
    'host_practice' => 'Host practice', 'sketch_comedy' => 'Comedy sketches / characters'];
const BOX2_TAGS = ['best_joke','good_premise','good_delivery','clip_this','invite_back','highlight','laundry'];

function consent(array $data): array
{
    $flags = [];
    foreach (['livestream','archive','clips','adaptation','feedback'] as $name) $flags[$name] = flag($data, $name . '_allowed');
    if ($flags['clips'] && !$flags['archive']) throw new InvalidArgumentException('Clips require archival recording permission.');
    if ($flags['archive'] && !$flags['livestream']) throw new InvalidArgumentException('Choose a private rehearsal for an unbroadcast set.');
    if ($flags['adaptation'] && !$flags['livestream']) throw new InvalidArgumentException('Private rehearsals cannot grant adaptation here.');
    $flags['level'] = !$flags['livestream'] ? 'private' : ($flags['clips'] ? 'clip_eligible' : 'live_only');
    return $flags;
}

function create_booking(array $data,bool $walkIn=false): array
{
    if ($walkIn) require_admin();
    if (!bookings_open()) throw new RuntimeException('Booking is not enabled. Please return after the host announces opening.', 503);
    if (!flag($data,'orientation_agreed') || !flag($data,'terms_agreed')) {
        throw new InvalidArgumentException('Acknowledge performer orientation and the terms before booking.');
    }
    if (field($data, 'orientation_version', 20) !== BOX2_TERMS) {
        throw new InvalidArgumentException('Performer orientation has changed. Review the current nine cards before booking.');
    }
    $stage = field($data,'stage_name',100,true);
    $full = field($data,'full_name',120);
    $email = email_field($data,'email');
    $phone = field($data,'phone',40);
    $social = field($data,'social_handle',100);
    $format = field($data,'performance_type',40,true);
    if (!isset(BOX2_FORMATS[$format])) throw new InvalidArgumentException('Choose an original comedy format.');
    $script = field($data,'teleprompter_text',5000);
    $permissions = consent($data);
    $slotId = filter_var($data['slot_id'] ?? null, FILTER_VALIDATE_INT);
    if (!$slotId || $slotId < 1) throw new InvalidArgumentException('Choose an available stage block.');
    $duration = filter_var($data['duration_minutes'] ?? 5, FILTER_VALIDATE_INT);
    if (!in_array($duration, set_lengths(), true)) throw new InvalidArgumentException('Choose an available 5, 10, or 15-minute set length.');
    $count = (int) ($duration / 5);
    return transaction(function () use ($stage,$full,$email,$phone,$social,$format,$script,$permissions,$slotId,$walkIn,$duration,$count): array {
        $blocks = reservable_blocks($slotId, $count, $permissions['level'] === 'private', $walkIn);
        $slot = $blocks[0];
        $id = bin2hex(random_bytes(12));
        query('INSERT INTO bookings(id,slot_id,stage_name,full_name,email,phone,social_handle,performance_type,
            consent_level,livestream_allowed,archive_allowed,clips_allowed,adaptation_allowed,feedback_allowed,
            teleprompter_text,terms_version,consented_at,orientation_version,created_at,updated_at,duration_minutes,block_count)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            [$id,$slotId,$stage,$full,$email,$phone,$social,$format,$permissions['level'],
             $permissions['livestream'],$permissions['archive'],$permissions['clips'],$permissions['adaptation'],$permissions['feedback'],
             $script,BOX2_TERMS,utc(),BOX2_TERMS,utc(),utc(),$duration,$count]);
        foreach ($blocks as $block) {
            if ($block['visibility'] === 'hold') query('UPDATE slots SET visibility=? WHERE id=?', [$permissions['level'] === 'private' ? 'private' : 'public', $block['id']]);
            query('INSERT INTO booking_allocations(booking_id,slot_id) VALUES (?,?)', [$id, $block['id']]);
        }
        $links = issue_booking_links($id,$slot['start_at_utc']);
        schedule_reminders($id,$links);
        if ($walkIn) audit('walk_in',$id);
        return ['booking' => booking_record($id), 'links' => $links];
    });
}

function reservable_blocks(int $slotId, int $count, bool $private, bool $walkIn): array
{
    $first = query('SELECT s.*,n.status AS night_status FROM slots s JOIN show_nights n ON n.id=s.show_night_id WHERE s.id=?', [$slotId])->fetch();
    if (!$first || $first['night_status'] !== 'open') throw new InvalidArgumentException('This show is not available.');
    $blocks = query('SELECT * FROM slots WHERE show_night_id=? AND start_at_utc>=? ORDER BY start_at_utc LIMIT ?',
        [$first['show_night_id'], $first['start_at_utc'], $count])->fetchAll();
    if (count($blocks) !== $count) throw new InvalidArgumentException('This set length does not fit before the show ends.');
    foreach ($blocks as $index => $block) {
        $expected = utc((new DateTimeImmutable($first['start_at_utc']))->modify('+' . ($index * 10) . ' minutes'));
        if ($block['start_at_utc'] !== $expected || strtotime($block['end_at_utc']) - strtotime($block['start_at_utc']) !== 600
            || $block['status'] !== 'open' || $block['start_at_utc'] <= utc()
            || ($block['visibility'] === 'hold' && !$walkIn)) {
            throw new InvalidArgumentException('This set length no longer fits consecutive open allocations.');
        }
        if ($block['visibility'] !== 'hold' && ($block['visibility'] === 'private') !== $private) {
            throw new InvalidArgumentException('Private rehearsals must use off-stream blocks; a set cannot cross recording modes.');
        }
        if (query('SELECT 1 FROM booking_allocations WHERE slot_id=? AND active=1', [$block['id']])->fetchColumn()) {
            throw new InvalidArgumentException('Part of this block was just booked. Choose another start time.');
        }
    }
    return $blocks;
}

function booking_record(string $id): array
{
    $booking = query('SELECT b.*,s.start_at_utc,s.end_at_utc,s.show_night_id,n.show_date,n.recording_mode,
        (SELECT max(allocated.end_at_utc) FROM booking_allocations a JOIN slots allocated ON allocated.id=a.slot_id WHERE a.booking_id=b.id) AS reservation_end_at_utc
        FROM bookings b JOIN slots s ON s.id=b.slot_id JOIN show_nights n ON n.id=s.show_night_id WHERE b.id=?',[$id])->fetch();
    if (!$booking) throw new InvalidArgumentException('Booking not found.');
    $booking['stage_end_at_utc'] = utc((new DateTimeImmutable($booking['start_at_utc']))->modify('+' . $booking['duration_minutes'] . ' minutes'));
    return $booking;
}

function issue_booking_links(string $id,string $stage): array
{
    $links=[];
    foreach (['confirm','cancel'] as $purpose) {
        $token=bin2hex(random_bytes(32));
        query('INSERT INTO booking_tokens(booking_id,token_hash,purpose,expires_at) VALUES (?,?,?,?)',
            [$id,hash('sha256',$token),$purpose,utc((new DateTimeImmutable($stage))->modify('+1 day'))]);
        $signature=hash_hmac('sha256',$purpose.':'.$token,config()['secret']);
        $links[$purpose]=url('/respond?'.http_build_query(['action'=>$purpose,'token'=>$token,'signature'=>$signature]));
    }
    return $links;
}

function authorized_token(array $data): array
{
    $purpose=field($data,'action',10,true);
    $token=field($data,'token',64,true);
    $signature=field($data,'signature',64,true);
    if (!in_array($purpose,['confirm','cancel'],true) || !preg_match('/^[a-f0-9]{64}$/D',$token)
        || !hash_equals(hash_hmac('sha256',$purpose.':'.$token,config()['secret']),$signature)) {
        throw new InvalidArgumentException('Invalid booking link.');
    }
    $record=query('SELECT * FROM booking_tokens WHERE token_hash=? AND purpose=? AND used_at IS NULL AND expires_at>?',
        [hash('sha256',$token),$purpose,utc()])->fetch();
    if (!$record) throw new InvalidArgumentException('This link expired or was already used.');
    return $record;
}

function apply_booking_link(array $data): array
{
    return transaction(function () use ($data): array {
        $token=authorized_token($data);
        $booking=booking_record($token['booking_id']);
        if (!in_array($booking['status'],['booked','confirmed'],true)) throw new InvalidArgumentException('This booking can no longer be changed with this link. Contact the host.');
        $status=$token['purpose']==='confirm'?'confirmed':'cancelled';
        query('UPDATE bookings SET status=?,updated_at=? WHERE id=?',[$status,utc(),$booking['id']]);
        query('UPDATE booking_tokens SET used_at=? WHERE id=?',[utc(),$token['id']]);
        if ($status==='cancelled') {
            query('UPDATE booking_tokens SET used_at=? WHERE booking_id=? AND used_at IS NULL',[utc(),$booking['id']]);
            query("UPDATE reminders SET status='skipped' WHERE booking_id=? AND status IN ('pending','failed','disabled')",[$booking['id']]);
        }
        return booking_record($booking['id']);
    });
}

function host_booking_action(string $id,string $action,string $note='',bool $noArchiveConfirmed=false): void
{
    require_admin();
    transaction(function () use ($id,$action,$note,$noArchiveConfirmed): void {
        $booking=booking_record($id);
        if ($action==='note') {
            if (mb_strlen($note)>1000) throw new InvalidArgumentException('Host note is too long.');
            query('UPDATE bookings SET host_note=?,updated_at=? WHERE id=?',[$note,utc(),$id]);
        } elseif (in_array($action,['checked_in','no_show','performed','cancelled'],true)) {
            if (in_array($booking['status'],['cancelled','performed'],true)) throw new InvalidArgumentException('This booking is already closed.');
            if ($action==='checked_in') {
                $required=$booking['consent_level']==='private'?'confirmed_off':'public';
                if ($booking['recording_mode']!==$required) {
                    throw new InvalidArgumentException('Set the host recording mode first. Private rehearsal requires actual streaming AND recording stopped.');
                }
                if ($booking['livestream_allowed'] && !$booking['archive_allowed'] && !$noArchiveConfirmed) {
                    throw new InvalidArgumentException('Confirm Twitch VOD and local recording are disabled for this live-only set before check-in.');
                }
                $other=query("SELECT b.id FROM bookings b JOIN slots s ON s.id=b.slot_id WHERE s.show_night_id=? AND b.status='checked_in' AND b.consent_level='private' AND b.id!=?",[$booking['show_night_id'],$id])->fetchColumn();
                if ($other) throw new InvalidArgumentException('Finish the checked-in private rehearsal before another set enters.');
            }
            query('UPDATE bookings SET status=?,check_in_at=CASE WHEN ?=\'checked_in\' THEN ? ELSE check_in_at END,
                performed_at=CASE WHEN ?=\'performed\' THEN ? ELSE performed_at END,updated_at=? WHERE id=?',
                [$action,$action,utc(),$action,utc(),utc(),$id]);
            if (in_array($action,['cancelled','no_show','performed'],true)) {
                query("UPDATE reminders SET status='skipped' WHERE booking_id=? AND status IN ('pending','failed','disabled')",[$id]);
            }
        } elseif (in_array($action,BOX2_TAGS,true)) {
            if (in_array($action,['clip_this','highlight','laundry'],true) && !$booking['clips_allowed']) {
                throw new InvalidArgumentException('This performer did not permit BOX2 highlight clips.');
            }
            if (query('SELECT 1 FROM clip_candidates WHERE booking_id=? AND tag=?',[$id,$action])->fetchColumn()) {
                query('DELETE FROM clip_candidates WHERE booking_id=? AND tag=?',[$id,$action]);
            } else query('INSERT INTO clip_candidates(booking_id,tag) VALUES (?,?)',[$id,$action]);
        } else throw new InvalidArgumentException('Unknown host action.');
        audit('booking_'.$action,$id);
    });
}

function set_recording_mode(int $night,string $mode): void
{
    require_admin();
    if (!in_array($mode,['public','confirmed_off'],true)) throw new InvalidArgumentException('Invalid recording mode.');
    transaction(function () use ($night,$mode): void {
        if ($mode==='public' && query("SELECT 1 FROM bookings b JOIN slots s ON s.id=b.slot_id WHERE s.show_night_id=? AND b.status='checked_in' AND b.consent_level='private'",[$night])->fetchColumn()) {
            throw new InvalidArgumentException('Finish or cancel the private rehearsal before resuming public broadcast.');
        }
        query('UPDATE show_nights SET recording_mode=?,recording_confirmed_at=? WHERE id=?',[$mode,utc(),$night]);
        audit('recording_'.$mode,(string)$night);
    });
}

function submit_writer(array $data): array
{
    if (!forms_ready()) throw new RuntimeException('Secure submissions are unavailable.',503);
    if (!flag($data,'terms_agreed')) throw new InvalidArgumentException('Accept the writer terms first.');
    $text=field($data,'text',10000,true);
    $alias=field($data,'alias',100,true);
    $contact=email_field($data,'contact',false);
    $credit=field($data,'credit',100);
    $id=bin2hex(random_bytes(12));
    $token=bin2hex(random_bytes(32));
    query('INSERT INTO writer_submissions(id,text,alias,contact,credit,perform_allowed,publish_allowed,ai_allowed,music_allowed,
        withdrawal_hash,terms_version,consented_at,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
        [$id,$text,$alias,$contact,$credit,flag($data,'perform_allowed'),flag($data,'publish_allowed'),flag($data,'ai_allowed'),flag($data,'music_allowed'),
         hash('sha256',$token),BOX2_TERMS,utc(),utc()]);
    return ['id'=>$id,'withdrawal'=>url('/withdraw?token='.$token)];
}

function withdraw_writer(string $token): void
{
    if (!preg_match('/^[a-f0-9]{64}$/D',$token)) throw new InvalidArgumentException('Invalid withdrawal link.');
    $updated=query("UPDATE writer_submissions SET status='withdrawn' WHERE withdrawal_hash=? AND status='submitted'",[hash('sha256',$token)]);
    if (!$updated->rowCount()) throw new InvalidArgumentException('This request is unavailable or production has already begun. Contact the host for later changes.');
}

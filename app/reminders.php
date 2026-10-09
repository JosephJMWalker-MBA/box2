<?php
declare(strict_types=1);

function schedule_reminders(string $id,array $links): void
{
    $booking=booking_record($id);
    $stage=new DateTimeImmutable($booking['start_at_utc']);
    $check=$stage->modify('-20 minutes');
    $day=local_instant($booking['show_date'],'14:00');
    $due=['confirmation'=>new DateTimeImmutable(), 'day_of'=>$day,'two_hours'=>$stage->modify('-2 hours'),
        'check_in_30'=>$check->modify('-30 minutes'),'stage_10'=>$stage->modify('-10 minutes')];
    $body="BOX2 - Come Tell It Here First\nBooking code: {$id}\nShow evening: {$booking['show_date']}\n"
        .'Stage date/time: '.local_label($booking['start_at_utc'])."\nFive-minute set in a ten-minute allocation.\n"
        .'Check in: '.local_label(utc($check))."\nRecording permission: {$booking['consent_level']}\n"
        .(config()['venue_public_enabled']?'Venue: '.config()['venue_address']."\nArrival: ".config()['arrival_text']."\n":'Venue details are not yet approved for publication.'."\n")
        .'Orientation: '.url('/rules')."\nTwitch: https://www.twitch.tv/".config()['twitch_channel']."\n"
        .'Confirm: '.$links['confirm']."\nCancel: ".$links['cancel']."\n";
    foreach ($due as $type=>$date) {
        if ($type!=='confirmation' && utc($date)<=utc()) continue;
        query('INSERT INTO reminders(booking_id,type,due_at_utc,status,payload) VALUES (?,?,?,?,?)',
            [$id,$type,utc($date),config()['mail_transport']==='disabled'?'disabled':'pending',
             json_encode(['subject'=>'BOX2 '.$type.' - '.local_label($booking['start_at_utc']),'body'=>$body],JSON_THROW_ON_ERROR)]);
    }
}

function process_reminders(?callable $transport=null): array
{
    $counts=['accepted'=>0,'failed'=>0,'disabled'=>0,'skipped'=>0,'uncertain'=>0];
    // A crashed worker may have sent the message. Do not blindly redeliver.
    $counts['uncertain']=query("UPDATE reminders SET status='uncertain',error_message='Interrupted send; manual provider verification required.'
        WHERE status='sending' AND claimed_at<?",[utc((new DateTimeImmutable())->modify('-15 minutes'))])->rowCount();
    for ($i=0;$i<50;$i++) {
        $reminder=transaction(function (): array|false {
            $row=query("SELECT r.*,b.email,b.status AS booking_status,s.start_at_utc FROM reminders r JOIN bookings b ON b.id=r.booking_id
                JOIN slots s ON s.id=b.slot_id WHERE r.status IN ('pending','failed','disabled') AND r.attempt_count<3
                AND r.due_at_utc<=? ORDER BY r.due_at_utc LIMIT 1",[utc()])->fetch();
            if (!$row) return false;
            if (in_array($row['booking_status'],['cancelled','no_show','performed'],true)
                || ($row['type']!=='confirmation' && $row['start_at_utc']<=utc())) {
                query("UPDATE reminders SET status='skipped' WHERE id=?",[$row['id']]);$row['skip']=true;return $row;
            }
            if (config()['mail_transport']==='disabled') {
                query("UPDATE reminders SET status='disabled' WHERE id=?",[$row['id']]);$row['disabled']=true;return $row;
            }
            $row['claim_id']=bin2hex(random_bytes(16));
            query("UPDATE reminders SET status='sending',claim_id=?,claimed_at=?,attempt_count=attempt_count+1 WHERE id=?",
                [$row['claim_id'],utc(),$row['id']]);
            return $row;
        });
        if (!$reminder) break;
        if (isset($reminder['skip'])) {$counts['skipped']++;continue;}
        if (isset($reminder['disabled'])) {$counts['disabled']++;break;}
        try {
            $payload=json_decode($reminder['payload'],true,512,JSON_THROW_ON_ERROR);
            ($transport??'send_mail')($reminder['email'],$payload['subject'],$payload['body']);
            query("UPDATE reminders SET status='accepted',sent_at=?,error_message='' WHERE id=? AND claim_id=?",
                [utc(),$reminder['id'],$reminder['claim_id']]);
            $counts['accepted']++;
        } catch (Throwable $exception) {
            // Never persist provider responses, recipient PII or content in diagnostics.
            query("UPDATE reminders SET status='failed',error_message='Transport rejected or could not verify acceptance.',due_at_utc=? WHERE id=? AND claim_id=?",
                [utc((new DateTimeImmutable())->modify('+'.(5*2**(int)$reminder['attempt_count']).' minutes')),$reminder['id'],$reminder['claim_id']]);
            $counts['failed']++;
        }
    }
    return $counts;
}

function send_mail(string $to,string $subject,string $body): void
{
    $settings=config();
    if (!filter_var($to,FILTER_VALIDATE_EMAIL) || !filter_var($settings['email_from'],FILTER_VALIDATE_EMAIL)
        || strpbrk($subject,"\r\n")!==false) throw new RuntimeException('Invalid mail configuration.');
    $headers='From: '.$settings['email_from']."\r\nMIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\n";
    $encodedSubject='=?UTF-8?B?'.base64_encode($subject).'?=';
    if ($settings['mail_transport']==='local') {
        if (!mail($to,$encodedSubject,$body,$headers)) throw new RuntimeException('Local transport failed.');
        return;
    }
    if ($settings['mail_transport']!=='smtp' || !preg_match('/^[a-zA-Z0-9.-]+$/D',$settings['smtp_host'])) {
        throw new RuntimeException('Mail transport is unavailable.');
    }
    $context=stream_context_create(['ssl'=>['verify_peer'=>true,'verify_peer_name'=>true,'peer_name'=>$settings['smtp_host']]]);
    $socket=stream_socket_client('tcp://'.$settings['smtp_host'].':'.(int)$settings['smtp_port'],$errno,$error,15,STREAM_CLIENT_CONNECT,$context);
    if (!$socket) throw new RuntimeException('SMTP connection failed.');
    stream_set_timeout($socket,15);
    $read=function (array $allowed) use ($socket): void {
        do {$line=fgets($socket,1024);if ($line===false) throw new RuntimeException('SMTP connection ended.');}
        while (isset($line[3]) && $line[3]==='-');
        if (!in_array((int)substr($line,0,3),$allowed,true)) throw new RuntimeException('SMTP command rejected.');
    };
    $command=function (string $line,array $allowed) use ($socket,$read): void {fwrite($socket,$line."\r\n");$read($allowed);};
    try {
        $read([220]);$command('EHLO box2',[250]);$command('STARTTLS',[220]);
        if (!stream_socket_enable_crypto($socket,true,STREAM_CRYPTO_METHOD_TLS_CLIENT)) throw new RuntimeException('SMTP TLS failed.');
        $command('EHLO box2',[250]);
        if ($settings['smtp_username']!=='') {
            $command('AUTH LOGIN',[334]);$command(base64_encode($settings['smtp_username']),[334]);
            $command(base64_encode($settings['smtp_password']),[235]);
        }
        $command('MAIL FROM:<'.$settings['email_from'].'>',[250]);$command('RCPT TO:<'.$to.'>',[250,251]);$command('DATA',[354]);
        $message=$headers.'To: '.$to."\r\nSubject: ".$encodedSubject."\r\n\r\n".$body;
        $message=str_replace(["\r\n","\r"],"\n",$message);
        $message=preg_replace('/^\./m','..',$message);
        fwrite($socket,str_replace("\n","\r\n",$message)."\r\n.\r\n");$read([250]);
        // Acceptance is durable before QUIT; a QUIT disconnect must not trigger redelivery.
        fwrite($socket,"QUIT\r\n");
    } finally {fclose($socket);}
}

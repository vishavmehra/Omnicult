export type Language = { code: string; name: string; script: string; sample: string };

/**
 * Languages the preview tool offers, each with the script the server has a bundled Noto font for. The sample lines are
 * common festival greetings for checking how a script lays out in a box. They are not campaign copy and have not been
 * reviewed by a native speaker.
 */
export const LANGUAGES: Language[] = [
  { code: "mr", name: "Marathi", script: "Deva", sample: "दिवाळी म्हणजे फराळ!" },
  { code: "hi", name: "Hindi", script: "Deva", sample: "दीपावली की हार्दिक शुभकामनाएँ" },
  { code: "ta", name: "Tamil", script: "Taml", sample: "இனிய தீபாவளி நல்வாழ்த்துகள்" },
  { code: "ml", name: "Malayalam", script: "Mlym", sample: "ദീപാവലി ആശംസകൾ" },
  { code: "bn", name: "Bengali", script: "Beng", sample: "শুভ দীপাবলি" },
  { code: "te", name: "Telugu", script: "Telu", sample: "దీపావళి శుభాకాంక్షలు" },
  { code: "kn", name: "Kannada", script: "Knda", sample: "ದೀಪಾವಳಿಯ ಶುಭಾಶಯಗಳು" },
  { code: "gu", name: "Gujarati", script: "Gujr", sample: "દિવાળીની શુભેચ્છાઓ" },
  { code: "pa", name: "Punjabi", script: "Guru", sample: "ਦੀਵਾਲੀ ਦੀਆਂ ਵਧਾਈਆਂ" },
  { code: "or", name: "Odia", script: "Orya", sample: "ଦୀପାବଳିର ଶୁଭେଚ୍ଛା" },
  { code: "en", name: "English", script: "Latn", sample: "Diwali means faral" },
];

export const SCRIPT_NAME: Record<string, string> = {
  Deva: "Devanagari",
  Taml: "Tamil",
  Mlym: "Malayalam",
  Beng: "Bengali",
  Telu: "Telugu",
  Knda: "Kannada",
  Gujr: "Gujarati",
  Guru: "Gurmukhi",
  Orya: "Odia",
  Latn: "Latin",
};

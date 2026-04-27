import Foundation

/// Single serial queue shared by all on-disk stores under ``~/.syscontrol``.
/// Writes from different stores hit the same disk, so one queue serialises
/// them in submission order and avoids races between readers and writers in
/// the same process.
enum StorageQueue {
    static let shared = DispatchQueue(label: "com.syscontrol.storage.writes")
}

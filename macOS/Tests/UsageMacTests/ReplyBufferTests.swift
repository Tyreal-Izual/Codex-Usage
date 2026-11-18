import XCTest
@testable import UsageMac

final class ReplyBufferTests: XCTestCase {
    func testPartialUTF8AndMultipleRepliesRemainOrdered() {
        let input = Data("{\"text\":\"你好\"}\n{\"id\":2}\npartial".utf8)
        var buffer = ReplyBuffer()
        XCTAssertTrue(buffer.append(input.prefix(11)))
        XCTAssertNil(buffer.nextLine())
        XCTAssertTrue(buffer.append(input.dropFirst(11)))
        XCTAssertEqual(buffer.nextLine(), Data("{\"text\":\"你好\"}".utf8))
        XCTAssertEqual(buffer.nextLine(), Data("{\"id\":2}".utf8))
        XCTAssertNil(buffer.nextLine())
        XCTAssertEqual(buffer.pendingBytes, 7)
        XCTAssertTrue(buffer.append(Data("-end\n".utf8)))
        XCTAssertEqual(buffer.nextLine(), Data("partial-end".utf8))
        XCTAssertEqual(buffer.pendingBytes, 0)
    }

    func testOversizeChunkDoesNotGrowBufferAndResetDropsPartialData() {
        var buffer = ReplyBuffer(limit: 8)
        XCTAssertTrue(buffer.append(Data("12345".utf8)))
        XCTAssertFalse(buffer.append(Data("6789".utf8)))
        XCTAssertEqual(buffer.pendingBytes, 5)
        buffer.reset()
        XCTAssertEqual(buffer.pendingBytes, 0)
        XCTAssertTrue(buffer.append(Data("ok\n".utf8)))
        XCTAssertEqual(buffer.nextLine(), Data("ok".utf8))
    }

    func testBurstDrainsFullyAndCanAcceptAnotherBurst() {
        var buffer = ReplyBuffer()
        let input = (0..<1000).map { "\($0)\n" }.joined()
        for _ in 0..<2 {
            XCTAssertTrue(buffer.append(Data(input.utf8)))
            for index in 0..<1000 { XCTAssertEqual(buffer.nextLine(), Data(String(index).utf8)) }
            XCTAssertNil(buffer.nextLine())
            XCTAssertEqual(buffer.pendingBytes, 0)
        }
    }
}
